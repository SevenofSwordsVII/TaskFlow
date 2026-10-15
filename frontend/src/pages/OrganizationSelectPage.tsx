import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuthStore, UserMeOrganization } from "../store/authStore";
import { apiClient } from "../api/client";

export const OrganizationSelectPage: React.FC = () => {
  const navigate = useNavigate();
  const {
    user,
    organizations,
    setOrganizations,
    setCurrentOrganization,
    logout,
    fetchMe,
  } = useAuthStore();

  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isCreating, setIsCreating] = useState(false);

  useEffect(() => {
    fetchMe();
  }, [fetchMe]);

  const handleNameChange = (val: string) => {
    setName(val);
    const generatedSlug = val
      .toLowerCase()
      .trim()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "");
    setSlug(generatedSlug);
  };

  const handleSelectOrg = (org: UserMeOrganization) => {
    setCurrentOrganization(org);
    navigate("/");
  };

  const handleCreateOrg = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setIsLoading(true);

    try {
      const newOrg = await apiClient<UserMeOrganization>("/organizations", {
        method: "POST",
        body: JSON.stringify({
          name: name.trim(),
          slug: slug.trim().toLowerCase(),
        }),
      });

      const updated = [...organizations, newOrg];
      setOrganizations(updated);
      setCurrentOrganization(newOrg);
      navigate("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create organization.");
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-slate-50 px-4 py-12 sm:px-6 lg:px-8">
      <div className="w-full max-w-lg space-y-8 rounded-xl bg-white p-8 shadow-sm border border-slate-200">
        <div className="flex items-center justify-between border-b pb-4">
          <div>
            <h2 className="text-2xl font-bold tracking-tight text-slate-900">
              Workspaces
            </h2>
            <p className="text-sm text-slate-500">
              Signed in as {user?.email}
            </p>
          </div>
          <button
            onClick={() => logout().then(() => navigate("/login"))}
            className="text-xs font-medium text-slate-500 hover:text-red-600 transition"
          >
            Sign out
          </button>
        </div>

        {error && (
          <div className="rounded-md bg-red-50 p-4 text-sm text-red-700 border border-red-200">
            {error}
          </div>
        )}

        {organizations.length > 0 && !isCreating && (
          <div className="space-y-4">
            <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-500">
              Select an Organization
            </h3>
            <div className="divide-y divide-slate-100 rounded-lg border border-slate-200">
              {organizations.map((org) => (
                <div
                  key={org.id}
                  onClick={() => handleSelectOrg(org)}
                  className="flex cursor-pointer items-center justify-between p-4 hover:bg-slate-50 transition"
                >
                  <div>
                    <h4 className="font-medium text-slate-900">{org.name}</h4>
                    <p className="text-xs text-slate-500">/{org.slug}</p>
                  </div>
                  <span className="rounded bg-indigo-50 px-2.5 py-0.5 text-xs font-semibold text-indigo-700">
                    {org.role}
                  </span>
                </div>
              ))}
            </div>
            <button
              onClick={() => setIsCreating(true)}
              className="w-full rounded-md border border-slate-300 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
            >
              + Create new organization
            </button>
          </div>
        )}

        {(organizations.length === 0 || isCreating) && (
          <form className="space-y-4" onSubmit={handleCreateOrg}>
            <div className="flex items-center justify-between">
              <h3 className="text-lg font-semibold text-slate-900">
                Create Organization
              </h3>
              {organizations.length > 0 && (
                <button
                  type="button"
                  onClick={() => setIsCreating(false)}
                  className="text-xs text-slate-500 hover:underline"
                >
                  Cancel
                </button>
              )}
            </div>

            <div>
              <label
                htmlFor="org-name"
                className="block text-sm font-medium text-slate-700 mb-1"
              >
                Organization Name
              </label>
              <input
                id="org-name"
                type="text"
                required
                value={name}
                onChange={(e) => handleNameChange(e.target.value)}
                placeholder="Acme Corp"
                className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none"
              />
            </div>

            <div>
              <label
                htmlFor="org-slug"
                className="block text-sm font-medium text-slate-700 mb-1"
              >
                URL Slug
              </label>
              <div className="flex rounded-md shadow-sm">
                <span className="inline-flex items-center rounded-l-md border border-r-0 border-slate-300 bg-slate-50 px-3 text-xs text-slate-500">
                  taskflow.app/
                </span>
                <input
                  id="org-slug"
                  type="text"
                  required
                  value={slug}
                  onChange={(e) => setSlug(e.target.value)}
                  placeholder="acme-corp"
                  className="w-full rounded-r-md border border-slate-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none"
                />
              </div>
            </div>

            <button
              type="submit"
              disabled={isLoading}
              className="w-full rounded-md bg-indigo-600 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
            >
              {isLoading ? "Creating..." : "Create Organization & Continue"}
            </button>
          </form>
        )}
      </div>
    </div>
  );
};
