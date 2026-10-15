import React, { useEffect } from "react";
import { Link, Navigate, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { useKanbanBoard } from "../features/kanban/hooks/useKanbanBoard";
import { Board } from "../features/kanban/components/Board";
import { NotificationInbox } from "../features/notifications/components/NotificationInbox";
import { useAuthStore } from "../store/authStore";

export const BoardPage: React.FC = () => {
  const { boardId: paramBoardId } = useParams<{ boardId: string }>();
  const [searchParams] = useSearchParams();
  const projectId = searchParams.get("project");
  const navigate = useNavigate();

  const { currentOrganization, user } = useAuthStore();
  const isReadOnly = currentOrganization?.role === "VIEWER";

  const {
    board,
    isLoading,
    error,
    handleDragEnd,
    addList,
    addTask,
    deleteTask,
  } = useKanbanBoard(paramBoardId, projectId);

  useEffect(() => {
    if (!paramBoardId && board?.id) {
      navigate(`/boards/${board.id}`, { replace: true });
    }
  }, [paramBoardId, board?.id, navigate]);

  if (!paramBoardId && !projectId) {
    return <Navigate to="/projects" replace />;
  }

  if (isLoading) {
    return (
      <div className="flex h-screen items-center justify-center bg-slate-50">
        <div className="text-sm font-medium text-slate-500">Loading Kanban board...</div>
      </div>
    );
  }

  if (error || !board) {
    return (
      <div className="flex h-screen flex-col items-center justify-center bg-slate-50 p-4">
        <div className="rounded-xl border border-red-200 bg-white p-6 shadow-sm text-center max-w-md">
          <h2 className="text-lg font-semibold text-slate-900">Failed to load board</h2>
          <p className="mt-2 text-sm text-slate-500">
            {error instanceof Error ? error.message : "The board could not be found."}
          </p>
          <Link
            to="/organizations/select"
            className="mt-4 inline-block rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700"
          >
            Back to workspaces
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-screen flex-col bg-slate-50">
      {/* Top Navigation Bar */}
      <header className="flex h-14 shrink-0 items-center justify-between border-b border-slate-200 bg-white px-6">
        <div className="flex items-center gap-4">
          <Link
            to="/organizations/select"
            className="text-sm font-bold text-indigo-600 hover:text-indigo-700"
          >
            TaskFlow
          </Link>
          <span className="text-slate-300">/</span>
          <span className="text-sm font-medium text-slate-600">
            {currentOrganization?.name || "Workspace"}
          </span>
          <span className="text-slate-300">/</span>
          <span className="text-sm font-semibold text-slate-900">{board.name}</span>
        </div>

        <div className="flex items-center gap-3 text-xs text-slate-500">
          <NotificationInbox />
          {isReadOnly && (
            <span className="rounded bg-amber-100 px-2.5 py-0.5 font-semibold text-amber-800">
              Read-Only (Viewer)
            </span>
          )}
          <span>{user?.email}</span>
        </div>
      </header>

      {/* Kanban Board Container */}
      <main className="flex-1 overflow-hidden p-6">
        <Board
          board={board}
          onDragEnd={handleDragEnd}
          onAddList={addList}
          onAddTask={addTask}
          onDeleteTask={deleteTask}
          isReadOnly={isReadOnly}
        />
      </main>
    </div>
  );
};
