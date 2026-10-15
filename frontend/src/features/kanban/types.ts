export interface TaskItem {
  id: string;
  title: string;
  priority: "LOW" | "MEDIUM" | "HIGH" | "URGENT" | string;
  version: number;
  ordering_key: string;
  assignee_id?: string | null;
  due_date?: string | null;
}

export interface ListItem {
  id: string;
  name: string;
  ordering_key: string;
  version: number;
  tasks: TaskItem[];
}

export interface BoardData {
  id: string;
  project_id: string;
  name: string;
  description?: string | null;
  lists: ListItem[];
}
