import React, { useState } from "react";
import { Droppable } from "@hello-pangea/dnd";
import { ListItem } from "../types";
import { TaskCard } from "./TaskCard";

interface ListColumnProps {
  list: ListItem;
  index: number;
  onAddTask: (listId: string, title: string) => Promise<void>;
  onDeleteTask?: (taskId: string) => void;
  isReadOnly?: boolean;
}

export const ListColumn: React.FC<ListColumnProps> = ({
  list,
  onAddTask,
  onDeleteTask,
  isReadOnly = false,
}) => {
  const [isAdding, setIsAdding] = useState(false);
  const [taskTitle, setTaskTitle] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleCreateTask = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!taskTitle.trim() || isSubmitting) return;

    try {
      setIsSubmitting(true);
      await onAddTask(list.id, taskTitle.trim());
      setTaskTitle("");
      setIsAdding(false);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="flex w-80 shrink-0 flex-col rounded-xl bg-slate-100/80 p-3 border border-slate-200/80">
      <div className="mb-3 flex items-center justify-between px-1">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-semibold text-slate-800">{list.name}</h3>
          <span className="flex h-5 min-w-5 items-center justify-center rounded-full bg-slate-200 px-1.5 text-xs font-medium text-slate-600">
            {list.tasks.length}
          </span>
        </div>
      </div>

      <Droppable droppableId={list.id} isDropDisabled={isReadOnly}>
        {(provided, snapshot) => (
          <div
            ref={provided.innerRef}
            {...provided.droppableProps}
            className={`flex-1 overflow-y-auto px-0.5 min-h-[120px] rounded-lg transition-colors ${
              snapshot.isDraggingOver ? "bg-indigo-50/50" : ""
            }`}
          >
            {list.tasks.map((task, idx) => (
              <TaskCard
                key={task.id}
                task={task}
                index={idx}
                onDelete={onDeleteTask}
                isReadOnly={isReadOnly}
              />
            ))}
            {provided.placeholder}
          </div>
        )}
      </Droppable>

      {!isReadOnly && (
        <div className="mt-2 pt-1 border-t border-slate-200/60">
          {isAdding ? (
            <form onSubmit={handleCreateTask} className="space-y-2">
              <textarea
                autoFocus
                value={taskTitle}
                onChange={(e) => setTaskTitle(e.target.value)}
                placeholder="Enter a title for this card..."
                rows={2}
                className="w-full rounded-lg border border-slate-300 p-2 text-sm shadow-sm focus:border-indigo-500 focus:outline-none"
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    handleCreateTask(e);
                  }
                }}
              />
              <div className="flex items-center gap-2">
                <button
                  type="submit"
                  disabled={isSubmitting || !taskTitle.trim()}
                  className="rounded-md bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
                >
                  {isSubmitting ? "Adding..." : "Add card"}
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setIsAdding(false);
                    setTaskTitle("");
                  }}
                  className="text-xs text-slate-500 hover:text-slate-800"
                >
                  Cancel
                </button>
              </div>
            </form>
          ) : (
            <button
              onClick={() => setIsAdding(true)}
              className="flex w-full items-center gap-1.5 rounded-lg py-1.5 px-2 text-xs font-medium text-slate-600 hover:bg-slate-200/70 hover:text-slate-900 transition"
            >
              <span className="text-sm leading-none">+</span> Add a card
            </button>
          )}
        </div>
      )}
    </div>
  );
};
