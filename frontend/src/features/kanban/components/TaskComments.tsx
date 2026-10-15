import React, { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useAuthStore } from "../../../store/authStore";
import { apiClient } from "../../../api/client";

interface TaskCommentsProps {
  taskId: string;
  taskTitle: string;
  isOpen: boolean;
  onClose: () => void;
  isReadOnly?: boolean;
}

interface CommentItem {
  id: string;
  task_id: string;
  organization_id: string;
  author_id: string;
  content: string;
  created_at: string;
  updated_at: string;
  author?: {
    id: string;
    email: string;
    full_name: string;
  };
}

export const TaskComments: React.FC<TaskCommentsProps> = ({
  taskId,
  taskTitle,
  isOpen,
  onClose,
  isReadOnly = false,
}) => {
  const queryClient = useQueryClient();
  const { user: currentUser } = useAuthStore();
  const [newContent, setNewContent] = useState("");
  const [editingCommentId, setEditingCommentId] = useState<string | null>(null);
  const [editContent, setEditContent] = useState("");

  const { data: comments = [], isLoading } = useQuery<CommentItem[]>({
    queryKey: ["taskComments", taskId],
    queryFn: async () => {
      const res = await apiClient<{ items: CommentItem[] }>(
        `/tasks/${taskId}/comments`
      );
      return res.items || [];
    },
    enabled: isOpen && !!taskId,
  });

  const createCommentMutation = useMutation({
    mutationFn: (content: string) =>
      apiClient<CommentItem>(`/tasks/${taskId}/comments`, {
        method: "POST",
        body: JSON.stringify({ content }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["taskComments", taskId] });
      setNewContent("");
    },
  });

  const updateCommentMutation = useMutation({
    mutationFn: ({ id, content }: { id: string; content: string }) =>
      apiClient<CommentItem>(`/comments/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ content }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["taskComments", taskId] });
      setEditingCommentId(null);
    },
  });

  const deleteCommentMutation = useMutation({
    mutationFn: (id: string) =>
      apiClient(`/comments/${id}`, {
        method: "DELETE",
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["taskComments", taskId] });
    },
  });

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="flex max-h-[85vh] w-full max-w-lg flex-col rounded-xl bg-white shadow-xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-gray-200 px-6 py-4">
          <div>
            <span className="text-xs font-semibold uppercase text-gray-500">
              Task Discussion
            </span>
            <h3 className="text-base font-bold text-gray-900">{taskTitle}</h3>
          </div>
          <button
            onClick={onClose}
            className="rounded p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-600"
          >
            ✕
          </button>
        </div>

        {/* Comments Feed */}
        <div className="flex-1 space-y-4 overflow-y-auto p-6">
          {isLoading ? (
            <div className="text-center text-sm text-gray-500">Loading comments...</div>
          ) : comments.length === 0 ? (
            <div className="text-center text-sm text-gray-400">
              No comments yet. Start the conversation!
            </div>
          ) : (
            comments.map((comment) => {
              const isAuthor = comment.author_id === currentUser?.id;
              const isEditing = editingCommentId === comment.id;

              return (
                <div
                  key={comment.id}
                  className="rounded-lg border border-gray-100 bg-gray-50/70 p-4"
                >
                  <div className="flex items-center justify-between">
                    <span className="font-semibold text-xs text-gray-800">
                      {comment.author?.full_name || "User"}
                    </span>
                    <span className="text-[10px] text-gray-400">
                      {new Date(comment.created_at).toLocaleTimeString([], {
                        hour: "2-digit",
                        minute: "2-digit",
                      })}
                    </span>
                  </div>

                  {isEditing ? (
                    <div className="mt-2 space-y-2">
                      <textarea
                        value={editContent}
                        onChange={(e) => setEditContent(e.target.value)}
                        rows={2}
                        className="w-full rounded border border-gray-300 p-2 text-sm focus:border-blue-500 focus:outline-none"
                      />
                      <div className="flex justify-end gap-2">
                        <button
                          onClick={() => setEditingCommentId(null)}
                          className="rounded px-2.5 py-1 text-xs text-gray-600 hover:bg-gray-200"
                        >
                          Cancel
                        </button>
                        <button
                          onClick={() =>
                            updateCommentMutation.mutate({
                              id: comment.id,
                              content: editContent,
                            })
                          }
                          className="rounded bg-blue-600 px-2.5 py-1 text-xs font-semibold text-white hover:bg-blue-700"
                        >
                          Save
                        </button>
                      </div>
                    </div>
                  ) : (
                    <p className="mt-1.5 whitespace-pre-wrap text-sm text-gray-700">
                      {comment.content}
                    </p>
                  )}

                  {!isReadOnly && isAuthor && !isEditing && (
                    <div className="mt-2 flex gap-3 text-[11px] text-gray-500">
                      <button
                        onClick={() => {
                          setEditingCommentId(comment.id);
                          setEditContent(comment.content);
                        }}
                        className="hover:text-blue-600"
                      >
                        Edit
                      </button>
                      <button
                        onClick={() => {
                          if (window.confirm("Delete this comment?")) {
                            deleteCommentMutation.mutate(comment.id);
                          }
                        }}
                        className="hover:text-red-600"
                      >
                        Delete
                      </button>
                    </div>
                  )}
                </div>
              );
            })
          )}
        </div>

        {/* New Comment Input */}
        {!isReadOnly && (
          <div className="border-t border-gray-200 p-4">
            <form
              onSubmit={(e) => {
                e.preventDefault();
                if (!newContent.trim() || createCommentMutation.isPending) return;
                createCommentMutation.mutate(newContent.trim());
              }}
              className="flex gap-2"
            >
              <input
                type="text"
                value={newContent}
                onChange={(e) => setNewContent(e.target.value)}
                placeholder="Write a comment..."
                className="flex-1 rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
              />
              <button
                type="submit"
                disabled={!newContent.trim() || createCommentMutation.isPending}
                className="rounded bg-blue-600 px-4 py-2 text-sm font-semibold text-white shadow hover:bg-blue-700 disabled:opacity-50"
              >
                Send
              </button>
            </form>
          </div>
        )}
      </div>
    </div>
  );
};
