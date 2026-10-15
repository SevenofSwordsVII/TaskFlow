import React, { useState } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "../api/client";
import { Project } from "./ProjectsPage";

interface ProjectMember {
  id: string;
  project_id: string;
  user_id: string;
  project_role: string;
  created_at: string;
  user?: {
    id: string;
    email: string;
    full_name: string;
  };
}

interface OrgMember {
  id: string;
  user_id: string;
  role: string;
  user?: {
    id: string;
    email: string;
    full_name: string;
  };
}

export const ProjectSettingsPage: React.FC = () => {
  const { projectId } = useParams<{ projectId: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [visibility, setVisibility] = useState<"ORG_PUBLIC" | "RESTRICTED">("ORG_PUBLIC");
  const [selectedUserId, setSelectedUserId] = useState("");
  const [selectedRole, setSelectedRole] = useState("MEMBER");
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const { data: project, isLoading: isProjectLoading } = useQuery<Project>({
    queryKey: ["project", projectId],
    queryFn: () => apiClient<Project>(`/projects/${projectId}`),
    enabled: !!projectId,
  });

  // Populate form on data arrival
  React.useEffect(() => {
    if (project) {
      setName(project.name);
      setDescription(project.description || "");
      setVisibility(project.visibility);
    }
  }, [project]);

  const { data: members = [] } = useQuery<ProjectMember[]>({
    queryKey: ["projectMembers", projectId],
    queryFn: async () => {
      const res = await apiClient<{ items: ProjectMember[] }>(
        `/projects/${projectId}/members`
      );
      return res.items || [];
    },
    enabled: !!projectId,
  });

  const { data: orgMembers = [] } = useQuery<OrgMember[]>({
    queryKey: ["orgMembers", project?.organization_id],
    queryFn: async () => {
      const res = await apiClient<{ items: OrgMember[] }>(
        `/organizations/${project!.organization_id}/members`
      );
      return res.items || [];
    },
    enabled: !!project?.organization_id,
  });

  const updateMutation = useMutation({
    mutationFn: (updates: {
      name: string;
      description?: string;
      visibility: "ORG_PUBLIC" | "RESTRICTED";
    }) =>
      apiClient<Project>(`/projects/${projectId}`, {
        method: "PATCH",
        body: JSON.stringify(updates),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["project", projectId] });
      alert("Project updated successfully!");
    },
    onError: (err: Error) => {
      setErrorMsg(err.message || "Failed to update project");
    },
  });

  const addMemberMutation = useMutation({
    mutationFn: (payload: { user_id: string; project_role: string }) =>
      apiClient<ProjectMember>(`/projects/${projectId}/members`, {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["projectMembers", projectId] });
      setSelectedUserId("");
      setErrorMsg(null);
    },
    onError: (err: Error) => {
      setErrorMsg(err.message || "Failed to add member");
    },
  });

  const removeMemberMutation = useMutation({
    mutationFn: (userId: string) =>
      apiClient(`/projects/${projectId}/members/${userId}`, {
        method: "DELETE",
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["projectMembers", projectId] });
    },
  });

  const deleteProjectMutation = useMutation({
    mutationFn: () =>
      apiClient(`/projects/${projectId}`, {
        method: "DELETE",
      }),
    onSuccess: () => {
      navigate("/projects");
    },
  });

  if (isProjectLoading || !project) {
    return <div className="p-8 text-gray-500">Loading project settings...</div>;
  }

  return (
    <div className="min-h-screen bg-gray-50 p-6 md:p-10">
      <div className="mx-auto max-w-4xl">
        <div className="mb-6 flex items-center justify-between">
          <div>
            <Link
              to="/projects"
              className="text-xs font-semibold text-blue-600 hover:underline"
            >
              ← Back to Projects
            </Link>
            <h1 className="mt-1 text-2xl font-bold text-gray-900">
              {project.name} Settings
            </h1>
          </div>
        </div>

        {errorMsg && (
          <div className="mb-6 rounded bg-red-50 p-4 text-sm text-red-700">
            {errorMsg}
          </div>
        )}

        {/* General Details */}
        <div className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm">
          <h2 className="text-lg font-bold text-gray-900">General Information</h2>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              updateMutation.mutate({
                name,
                description: description || undefined,
                visibility,
              });
            }}
            className="mt-4 space-y-4"
          >
            <div>
              <label className="block text-xs font-semibold uppercase text-gray-600">
                Project Name
              </label>
              <input
                type="text"
                required
                value={name}
                onChange={(e) => setName(e.target.value)}
                className="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
              />
            </div>

            <div>
              <label className="block text-xs font-semibold uppercase text-gray-600">
                Description
              </label>
              <textarea
                rows={3}
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                className="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
              />
            </div>

            <div>
              <label className="block text-xs font-semibold uppercase text-gray-600">
                Visibility Scope
              </label>
              <select
                value={visibility}
                onChange={(e) =>
                  setVisibility(e.target.value as "ORG_PUBLIC" | "RESTRICTED")
                }
                className="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
              >
                <option value="ORG_PUBLIC">Public (All workspace members)</option>
                <option value="RESTRICTED">Restricted (Explicit project members only)</option>
              </select>
            </div>

            <button
              type="submit"
              disabled={updateMutation.isPending}
              className="rounded bg-blue-600 px-4 py-2 text-sm font-semibold text-white shadow hover:bg-blue-700 disabled:opacity-50"
            >
              Save Changes
            </button>
          </form>
        </div>

        {/* Restricted Project Members Management */}
        {visibility === "RESTRICTED" && (
          <div className="mt-8 rounded-xl border border-gray-200 bg-white p-6 shadow-sm">
            <h2 className="text-lg font-bold text-gray-900">Project Members</h2>
            <p className="mt-1 text-sm text-gray-500">
              Only granted members can access this restricted project and its boards.
            </p>

            <form
              onSubmit={(e) => {
                e.preventDefault();
                if (!selectedUserId) return;
                addMemberMutation.mutate({
                  user_id: selectedUserId,
                  project_role: selectedRole,
                });
              }}
              className="mt-4 flex flex-wrap gap-3"
            >
              <select
                value={selectedUserId}
                onChange={(e) => setSelectedUserId(e.target.value)}
                className="rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
              >
                <option value="">Select workspace member...</option>
                {orgMembers
                  .filter((om) => !members.some((m) => m.user_id === om.user_id))
                  .map((om) => (
                    <option key={om.user_id} value={om.user_id}>
                      {om.user?.full_name || om.user_id} ({om.user?.email})
                    </option>
                  ))}
              </select>

              <select
                value={selectedRole}
                onChange={(e) => setSelectedRole(e.target.value)}
                className="rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
              >
                <option value="MEMBER">Member</option>
                <option value="PROJECT_ADMIN">Project Admin</option>
                <option value="VIEWER">Viewer</option>
              </select>

              <button
                type="submit"
                disabled={!selectedUserId || addMemberMutation.isPending}
                className="rounded bg-blue-600 px-4 py-2 text-sm font-semibold text-white shadow hover:bg-blue-700 disabled:opacity-50"
              >
                Add Member
              </button>
            </form>

            <div className="mt-6 divide-y divide-gray-100">
              {members.map((m) => (
                <div key={m.id} className="flex items-center justify-between py-3">
                  <div>
                    <p className="font-semibold text-gray-900">
                      {m.user?.full_name || "User"}
                    </p>
                    <p className="text-xs text-gray-500">{m.user?.email}</p>
                  </div>
                  <div className="flex items-center gap-3">
                    <span className="rounded bg-gray-100 px-2 py-0.5 text-xs font-semibold text-gray-700">
                      {m.project_role}
                    </span>
                    <button
                      onClick={() => removeMemberMutation.mutate(m.user_id)}
                      className="text-xs text-red-600 hover:underline"
                    >
                      Remove
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Danger Zone */}
        <div className="mt-8 rounded-xl border border-red-200 bg-red-50/50 p-6">
          <h2 className="text-base font-bold text-red-900">Danger Zone</h2>
          <p className="mt-1 text-sm text-red-700">
            Deleting this project will archive it and remove all associated Kanban boards.
          </p>
          <div className="mt-4">
            <button
              onClick={() => {
                if (window.confirm("Are you sure you want to delete this project?")) {
                  deleteProjectMutation.mutate();
                }
              }}
              className="rounded bg-red-600 px-4 py-2 text-sm font-semibold text-white shadow hover:bg-red-700"
            >
              Delete Project
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
