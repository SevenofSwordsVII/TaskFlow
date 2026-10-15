import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { DropResult } from "@hello-pangea/dnd";
import { apiClient } from "../../../api/client";
import { BoardData, ListItem, TaskItem } from "../types";

export function useKanbanBoard(boardId?: string, projectId?: string | null) {
  const queryClient = useQueryClient();

  const projectBoardsQuery = useQuery({
    queryKey: ["projectBoards", projectId],
    queryFn: () => apiClient<Array<{ id: string; name: string }>>(`/projects/${projectId}/boards`),
    enabled: !!projectId && !boardId,
  });

  const effectiveBoardId = boardId || projectBoardsQuery.data?.[0]?.id || "";
  const boardQueryKey = ["board", effectiveBoardId];

  const boardQuery = useQuery({
    queryKey: boardQueryKey,
    queryFn: () => apiClient<BoardData>(`/boards/${effectiveBoardId}`),
    enabled: !!effectiveBoardId,
  });

  const moveTaskMutation = useMutation({
    mutationFn: async ({
      taskId,
      targetListId,
      prevTaskId,
      nextTaskId,
      expectedVersion,
    }: {
      taskId: string;
      targetListId: string;
      prevTaskId: string | null;
      nextTaskId: string | null;
      expectedVersion: number;
    }) => {
      return apiClient<TaskItem>(`/tasks/${taskId}/move`, {
        method: "POST",
        body: JSON.stringify({
          target_list_id: targetListId,
          prev_task_id: prevTaskId,
          next_task_id: nextTaskId,
          expected_version: expectedVersion,
        }),
      });
    },
    onMutate: async (variables) => {
      // Cancel outgoing refetches so they don't overwrite optimistic update
      await queryClient.cancelQueries({ queryKey: boardQueryKey });

      const previousBoard = queryClient.getQueryData<BoardData>(boardQueryKey);

      if (previousBoard) {
        const nextLists = previousBoard.lists.map((l) => ({
          ...l,
          tasks: [...l.tasks],
        }));

        let movedTask: TaskItem | null = null;
        for (const l of nextLists) {
          const idx = l.tasks.findIndex((t) => t.id === variables.taskId);
          if (idx !== -1) {
            [movedTask] = l.tasks.splice(idx, 1);
            break;
          }
        }

        if (movedTask) {
          const destList = nextLists.find((l) => l.id === variables.targetListId);
          if (destList) {
            let insertIdx = destList.tasks.length;
            if (variables.prevTaskId) {
              const pIdx = destList.tasks.findIndex((t) => t.id === variables.prevTaskId);
              insertIdx = pIdx !== -1 ? pIdx + 1 : destList.tasks.length;
            } else if (variables.nextTaskId) {
              const nIdx = destList.tasks.findIndex((t) => t.id === variables.nextTaskId);
              insertIdx = nIdx !== -1 ? nIdx : 0;
            } else {
              insertIdx = 0;
            }
            destList.tasks.splice(insertIdx, 0, {
              ...movedTask,
              version: movedTask.version + 1,
            });
          }
        }

        queryClient.setQueryData<BoardData>(boardQueryKey, {
          ...previousBoard,
          lists: nextLists,
        });
      }

      return { previousBoard };
    },
    onError: (err, _variables, context) => {
      // Rollback to previous board state on 409 Conflict or any error
      if (context?.previousBoard) {
        queryClient.setQueryData(boardQueryKey, context.previousBoard);
      }
    },
    onSettled: () => {
      // Reconcile server state
      queryClient.invalidateQueries({ queryKey: boardQueryKey });
    },
  });

  const handleDragEnd = (result: DropResult) => {
    const { source, destination, draggableId } = result;
    if (!destination) return;
    if (
      source.droppableId === destination.droppableId &&
      source.index === destination.index
    ) {
      return;
    }

    const currentBoard = queryClient.getQueryData<BoardData>(boardQueryKey);
    if (!currentBoard) return;

    const sourceList = currentBoard.lists.find((l) => l.id === source.droppableId);
    const destList = currentBoard.lists.find((l) => l.id === destination.droppableId);
    if (!sourceList || !destList) return;

    const task = sourceList.tasks.find((t) => t.id === draggableId);
    if (!task) return;

    // Remaining items in destination list excluding moved task if same list
    const destTasks =
      source.droppableId === destination.droppableId
        ? destList.tasks.filter((t) => t.id !== draggableId)
        : [...destList.tasks];

    const prevTask = destination.index > 0 ? destTasks[destination.index - 1] : null;
    const nextTask =
      destination.index < destTasks.length ? destTasks[destination.index] : null;

    moveTaskMutation.mutate({
      taskId: draggableId,
      targetListId: destination.droppableId,
      prevTaskId: prevTask?.id || null,
      nextTaskId: nextTask?.id || null,
      expectedVersion: task.version,
    });
  };

  const addListMutation = useMutation({
    mutationFn: (name: string) =>
      apiClient<ListItem>(`/boards/${effectiveBoardId}/lists`, {
        method: "POST",
        body: JSON.stringify({ name }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: boardQueryKey });
    },
  });

  const addTaskMutation = useMutation({
    mutationFn: ({ listId, title }: { listId: string; title: string }) =>
      apiClient<TaskItem>(`/lists/${listId}/tasks`, {
        method: "POST",
        body: JSON.stringify({ title }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: boardQueryKey });
    },
  });

  const deleteTaskMutation = useMutation({
    mutationFn: (taskId: string) =>
      apiClient<void>(`/tasks/${taskId}`, {
        method: "DELETE",
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: boardQueryKey });
    },
  });

  const isResolvingProject = !!projectId && !boardId && projectBoardsQuery.isLoading;
  const isBoardLoading = !!effectiveBoardId && boardQuery.isLoading;
  const isLoading = isResolvingProject || isBoardLoading;

  const error =
    projectBoardsQuery.error ||
    boardQuery.error ||
    (!!projectId && !boardId && !projectBoardsQuery.isLoading && !effectiveBoardId
      ? new Error("No board found for this project.")
      : null);

  return {
    board: boardQuery.data,
    isLoading,
    error,
    handleDragEnd,
    addList: async (name: string) => {
      await addListMutation.mutateAsync(name);
    },
    addTask: async (listId: string, title: string) => {
      await addTaskMutation.mutateAsync({ listId, title });
    },
    deleteTask: (taskId: string) => {
      deleteTaskMutation.mutate(taskId);
    },
  };
}
