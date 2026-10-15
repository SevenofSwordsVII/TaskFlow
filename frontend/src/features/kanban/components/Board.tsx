import React, { useState } from "react";
import { DragDropContext, DropResult } from "@hello-pangea/dnd";
import { BoardData } from "../types";
import { ListColumn } from "./ListColumn";

interface BoardProps {
  board: BoardData;
  onDragEnd: (result: DropResult) => void;
  onAddList: (name: string) => Promise<void>;
  onAddTask: (listId: string, title: string) => Promise<void>;
  onDeleteTask?: (taskId: string) => void;
  isReadOnly?: boolean;
}

export const Board: React.FC<BoardProps> = ({
  board,
  onDragEnd,
  onAddList,
  onAddTask,
  onDeleteTask,
  isReadOnly = false,
}) => {
  const [isAddingList, setIsAddingList] = useState(false);
  const [listName, setListName] = useState("");
  const [isSubmittingList, setIsSubmittingList] = useState(false);

  const handleCreateList = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!listName.trim() || isSubmittingList) return;

    try {
      setIsSubmittingList(true);
      await onAddList(listName.trim());
      setListName("");
      setIsAddingList(false);
    } finally {
      setIsSubmittingList(false);
    }
  };

  return (
    <div className="flex h-full flex-col">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-slate-900">{board.name}</h1>
          {board.description && (
            <p className="text-xs text-slate-500">{board.description}</p>
          )}
        </div>
      </div>

      <DragDropContext onDragEnd={onDragEnd}>
        <div className="flex flex-1 items-start gap-4 overflow-x-auto pb-4">
          {board.lists.map((list, idx) => (
            <ListColumn
              key={list.id}
              list={list}
              index={idx}
              onAddTask={onAddTask}
              onDeleteTask={onDeleteTask}
              isReadOnly={isReadOnly}
            />
          ))}

          {!isReadOnly && (
            <div className="w-80 shrink-0">
              {isAddingList ? (
                <form
                  onSubmit={handleCreateList}
                  className="rounded-xl border border-slate-300 bg-slate-100 p-3 shadow-sm"
                >
                  <input
                    autoFocus
                    type="text"
                    value={listName}
                    onChange={(e) => setListName(e.target.value)}
                    placeholder="Enter list title..."
                    className="w-full rounded-md border border-slate-300 p-2 text-sm focus:border-indigo-500 focus:outline-none"
                  />
                  <div className="mt-2 flex items-center gap-2">
                    <button
                      type="submit"
                      disabled={isSubmittingList || !listName.trim()}
                      className="rounded-md bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
                    >
                      {isSubmittingList ? "Adding..." : "Add list"}
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        setIsAddingList(false);
                        setListName("");
                      }}
                      className="text-xs text-slate-500 hover:text-slate-800"
                    >
                      Cancel
                    </button>
                  </div>
                </form>
              ) : (
                <button
                  onClick={() => setIsAddingList(true)}
                  className="flex w-full items-center gap-2 rounded-xl border border-dashed border-slate-300 bg-slate-50/50 p-3 text-sm font-medium text-slate-600 hover:border-slate-400 hover:bg-slate-100 transition"
                >
                  <span className="text-base leading-none">+</span> Add another list
                </button>
              )}
            </div>
          )}
        </div>
      </DragDropContext>
    </div>
  );
};
