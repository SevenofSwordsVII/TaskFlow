import React, { useState } from "react";
import { Draggable } from "@hello-pangea/dnd";
import { TaskItem } from "../types";
import { TaskComments } from "./TaskComments";

interface TaskCardProps {
  task: TaskItem;
  index: number;
  onEdit?: (task: TaskItem) => void;
  onDelete?: (taskId: string) => void;
  isReadOnly?: boolean;
}

const priorityColors: Record<string, string> = {
  LOW: "bg-slate-100 text-slate-700 border-slate-200",
  MEDIUM: "bg-blue-50 text-blue-700 border-blue-200",
  HIGH: "bg-amber-50 text-amber-700 border-amber-200",
  URGENT: "bg-rose-50 text-rose-700 border-rose-200",
};

export const TaskCard: React.FC<TaskCardProps> = ({
  task,
  index,
  onDelete,
  isReadOnly = false,
}) => {
  const [isCommentsOpen, setIsCommentsOpen] = useState(false);

  return (
    <>
      <Draggable draggableId={task.id} index={index} isDragDisabled={isReadOnly}>
        {(provided, snapshot) => (
          <div
            ref={provided.innerRef}
            {...provided.draggableProps}
            {...provided.dragHandleProps}
            onClick={() => setIsCommentsOpen(true)}
            className={`group mb-2.5 cursor-pointer rounded-lg border bg-white p-3.5 shadow-sm transition hover:border-slate-300 hover:shadow ${
              snapshot.isDragging
                ? "border-indigo-400 shadow-lg ring-2 ring-indigo-400/20"
                : "border-slate-200"
            }`}
          >
            <div className="flex items-start justify-between gap-2">
              <h4 className="text-sm font-medium text-slate-900 leading-snug">
                {task.title}
              </h4>
              {!isReadOnly && onDelete && (
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    onDelete(task.id);
                  }}
                  className="opacity-0 group-hover:opacity-100 text-xs text-slate-400 hover:text-red-500 transition"
                  title="Delete task"
                >
                  ✕
                </button>
              )}
            </div>

            <div className="mt-2.5 flex items-center justify-between text-xs">
              <span
                className={`rounded border px-2 py-0.5 font-medium ${
                  priorityColors[task.priority] || priorityColors.MEDIUM
                }`}
              >
                {task.priority}
              </span>

              {task.due_date && (
                <span className="text-slate-400">
                  {new Date(task.due_date).toLocaleDateString(undefined, {
                    month: "short",
                    day: "numeric",
                  })}
                </span>
              )}
            </div>
          </div>
        )}
      </Draggable>

      <TaskComments
        taskId={task.id}
        taskTitle={task.title}
        isOpen={isCommentsOpen}
        onClose={() => setIsCommentsOpen(false)}
        isReadOnly={isReadOnly}
      />
    </>
  );
};
