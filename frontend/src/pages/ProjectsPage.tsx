import React, { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { useAuthStore } from "../store/authStore";
import { apiClient } from "../api/client";

export interface Project {
  id: string;
  organization_id: string;
  name: string;
  key: string;
  description: string | null;
  visibility: "ORG_PUBLIC" | "RESTRICTED";
  is_archived: boolean;
  created_at: string;
}

export const ProjectsPage: React.FC = () => {
  const queryClient = useQueryClient();
  const { currentOrganization } = useAuthStore();
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [name, setName] = useState("");
  const [key, setKey] = useState("");
  const [description, setDescription] = useState("");
  const [visibility, setVisibility] = useState<"ORG_PUBLIC" | "RESTRICTED">("ORG_PUBLIC");
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const isOrgAdmin =
    currentOrganization?.role === "OWNER" || currentOrganization?.role === "ADMIN";

  const { data: projects = [], isLoading } = useQuery<Project[]>({
    queryKey: ["projects", currentOrganization?.id],
    queryFn: () =>
      apiClient<Project[]>(`/organizations/${currentOrganization!.id}/projects`),
    enabled: !!currentOrganization?.id,
  });

  const createMutation = useMutation({
    mutationFn: (newProject: {
      name: string;
      key: string;
      description?: string;
      visibility: "ORG_PUBLIC" | "RESTRICTED";
    }) =>
      apiClient<Project>(`/organizations/${currentOrganization!.id}/projects`, {
        method: "POST",
        body: JSON.stringify(newProject),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["projects", currentOrganization?.id] });
      setIsModalOpen(false);
      setName("");
      setKey("");
      setDescription("");
      setErrorMsg(null);
    },
    onError: (err: Error) => {
      setErrorMsg(err.message || "Failed to create project");
    },
  });

  const handleCreate = (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim() || !key.trim()) return;
    createMutation.mutate({
      name: name.trim(),
      key: key.trim().toUpperCase(),
      description: description.trim() || undefined,
      visibility,
    });
  };

  if (!currentOrganization) {
    return (
      <div className="flex h-screen items-center justify-center bg-gray-50 p-4">
        <div className="text-center">
          <p className="text-gray-600 mb-4">No organization selected.</p>
          <Link
            to="/organizations"
            className="rounded bg-blue-600 px-4 py-2 font-medium text-white hover:bg-blue-700"
          >
            Select Organization
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50 p-6 md:p-10">
      <div className="mx-auto max-w-6xl">
        {/* Header */}
        <div className="mb-8 flex flex-col items-start justify-between gap-4 md:flex-row md:items-center">
          <div>
            <div className="flex items-center gap-3">
              <h1 className="text-2xl font-bold text-gray-900">Projects</h1>
              <span className="rounded bg-gray-200 px-2.5 py-0.5 text-xs font-semibold text-gray-700">
                {currentOrganization.name}
              </span>
            </div>
            <p className="mt-1 text-sm text-gray-500">
              Manage your organization initiatives and Kanban boards.
            </p>
          </div>

          <div className="flex items-center gap-3">
            <Link
              to="/settings/members"
              className="rounded border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 shadow-sm hover:bg-gray-50"
            >
              Members & Roles
            </Link>
            {isOrgAdmin && (
              <Link
                to="/settings/audit-logs"
                className="rounded border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 shadow-sm hover:bg-gray-50"
              >
                Audit Logs
              </Link>
            )}
            {isOrgAdmin && (
              <button
                onClick={() => setIsModalOpen(true)}
                className="rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white shadow hover:bg-blue-700"
              >
                + New Project
              </button>
            )}
          </div>
        </div>

        {/* Project Grid */}
        {isLoading ? (
          <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3">
            {[1, 2, 3].map((i) => (
              <div
                key={i}
                className="h-44 animate-pulse rounded-lg border border-gray-200 bg-white p-6 shadow-sm"
              />
            ))}
          </div>
        ) : projects.length === 0 ? (
          <div className="rounded-lg border-2 border-dashed border-gray-300 p-12 text-center">
            <h3 className="text-base font-semibold text-gray-900">No projects yet</h3>
            <p className="mt-1 text-sm text-gray-500">
              Get started by creating your team's first project.
            </p>
            {isOrgAdmin && (
              <div className="mt-6">
                <button
                  onClick={() => setIsModalOpen(true)}
                  className="rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white shadow hover:bg-blue-700"
                >
                  Create Project
                </button>
              </div>
            )}
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3">
            {projects.map((project) => (
              <div
                key={project.id}
                className="flex flex-col justify-between rounded-lg border border-gray-200 bg-white p-6 shadow-sm transition hover:shadow-md"
              >
                <div>
                  <div className="flex items-center justify-between">
                    <span className="rounded bg-blue-100 px-2 py-0.5 text-xs font-bold text-blue-800">
                      {project.key}
                    </span>
                    <span
                      className={`rounded px-2 py-0.5 text-xs font-medium ${
                        project.visibility === "RESTRICTED"
                          ? "bg-amber-100 text-amber-800"
                          : "bg-emerald-100 text-emerald-800"
                      }`}
                    >
                      {project.visibility === "RESTRICTED" ? "Restricted" : "Public"}
                    </span>
                  </div>
                  <h3 className="mt-3 text-lg font-bold text-gray-900">{project.name}</h3>
                  <p className="mt-1 line-clamp-2 text-sm text-gray-500">
                    {project.description || "No description provided."}
                  </p>
                </div>

                <div className="mt-6 flex items-center justify-between border-t border-gray-100 pt-4">
                  <Link
                    to={`/boards?project=${project.id}`}
                    className="text-sm font-semibold text-blue-600 hover:text-blue-800"
                  >
                    Open Board →
                  </Link>
                  {isOrgAdmin && (
                    <Link
                      to={`/projects/${project.id}/settings`}
                      className="text-xs text-gray-400 hover:text-gray-600"
                    >
                      Settings
                    </Link>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Create Project Modal */}
        {isModalOpen && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
            <div className="w-full max-w-md rounded-xl bg-white p-6 shadow-xl">
              <h2 className="text-xl font-bold text-gray-900">Create Project</h2>
              <p className="mt-1 text-sm text-gray-500">
                Organize work with a dedicated project key and visibility scope.
              </p>

              {errorMsg && (
                <div className="mt-4 rounded bg-red-50 p-3 text-sm text-red-700">
                  {errorMsg}
                </div>
              )}

              <form onSubmit={handleCreate} className="mt-5 space-y-4">
                <div>
                  <label className="block text-xs font-semibold uppercase text-gray-600">
                    Project Name
                  </label>
                  <input
                    type="text"
                    required
                    value={name}
                    onChange={(e) => {
                      setName(e.target.value);
                      if (!key) {
                        const autoKey = e.target.value
                          .replace(/[^a-zA-Z0-9]/g, "")
                          .slice(0, 4)
                          .toUpperCase();
                        setKey(autoKey);
                      }
                    }}
                    placeholder="e.g. Core Platform"
                    className="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
                  />
                </div>

                <div>
                  <label className="block text-xs font-semibold uppercase text-gray-600">
                    Project Key (2-20 uppercase chars)
                  </label>
                  <input
                    type="text"
                    required
                    maxLength={20}
                    value={key}
                    onChange={(e) => setKey(e.target.value.toUpperCase())}
                    placeholder="e.g. CORE"
                    className="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm font-mono focus:border-blue-500 focus:outline-none"
                  />
                </div>

                <div>
                  <label className="block text-xs font-semibold uppercase text-gray-600">
                    Description
                  </label>
                  <textarea
                    rows={2}
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                    placeholder="Optional project scope"
                    className="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
                  />
                </div>

                <div>
                  <label className="block text-xs font-semibold uppercase text-gray-600">
                    Visibility
                  </label>
                  <select
                    value={visibility}
                    onChange={(e) =>
                      setVisibility(e.target.value as "ORG_PUBLIC" | "RESTRICTED")
                    }
                    className="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
                  >
                    <option value="ORG_PUBLIC">Public (All workspace members)</option>
                    <option value="RESTRICTED">Restricted (Explicit members only)</option>
                  </select>
                </div>

                <div className="mt-6 flex justify-end gap-3 pt-2">
                  <button
                    type="button"
                    onClick={() => setIsModalOpen(false)}
                    className="rounded px-4 py-2 text-sm font-medium text-gray-600 hover:bg-gray-100"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    disabled={createMutation.isPending}
                    className="rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white shadow hover:bg-blue-700 disabled:opacity-50"
                  >
                    {createMutation.isPending ? "Creating..." : "Create Project"}
                  </button>
                </div>
              </form>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
