import React from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { useAuthStore } from "../store/authStore";
import { apiClient } from "../api/client";

interface AuditLogItem {
  id: string;
  organization_id: string;
  actor_id: string | null;
  action: string;
  target_type: string;
  target_id: string | null;
  payload: Record<string, unknown> | null;
  ip_address: string | null;
  user_agent: string | null;
  created_at: string;
  actor?: {
    id: string;
    email: string;
    full_name: string;
  };
}

export const AuditLogsPage: React.FC = () => {
  const { currentOrganization } = useAuthStore();
  const orgId = currentOrganization?.id;
  const isOrgAdmin =
    currentOrganization?.role === "OWNER" || currentOrganization?.role === "ADMIN";

  const { data, isLoading } = useQuery<{ items: AuditLogItem[] }>({
    queryKey: ["auditLogs", orgId],
    queryFn: () =>
      apiClient<{ items: AuditLogItem[] }>(
        `/organizations/${orgId}/audit-logs`
      ),
    enabled: !!orgId && isOrgAdmin,
  });

  const logs = data?.items || [];

  if (!isOrgAdmin) {
    return (
      <div className="flex h-screen items-center justify-center bg-gray-50 p-4">
        <div className="rounded-xl border border-red-200 bg-white p-6 shadow-sm text-center max-w-md">
          <h2 className="text-lg font-bold text-red-900">Access Denied</h2>
          <p className="mt-2 text-sm text-gray-600">
            Audit log inspection is restricted exclusively to organization administrators.
          </p>
          <Link
            to="/projects"
            className="mt-4 inline-block rounded bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700"
          >
            Back to Projects
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50 p-6 md:p-10">
      <div className="mx-auto max-w-6xl">
        {/* Header */}
        <div className="mb-6 flex items-center justify-between">
          <div>
            <Link
              to="/projects"
              className="text-xs font-semibold text-blue-600 hover:underline"
            >
              ← Back to Projects
            </Link>
            <h1 className="mt-1 text-2xl font-bold text-gray-900">
              Governance Audit Log
            </h1>
            <p className="mt-1 text-sm text-gray-500">
              Immutable, append-only record of security and lifecycle actions.
            </p>
          </div>
        </div>

        {/* Audit Logs Table */}
        <div className="overflow-hidden rounded-xl border border-gray-200 bg-white shadow-sm">
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200 text-left text-xs">
              <thead className="bg-gray-50/70 font-semibold uppercase text-gray-600">
                <tr>
                  <th className="px-6 py-3.5">Timestamp</th>
                  <th className="px-6 py-3.5">Action</th>
                  <th className="px-6 py-3.5">Target</th>
                  <th className="px-6 py-3.5">Actor</th>
                  <th className="px-6 py-3.5">IP / Client</th>
                  <th className="px-6 py-3.5">Payload</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 bg-white">
                {isLoading ? (
                  <tr>
                    <td colSpan={6} className="px-6 py-8 text-center text-gray-500">
                      Loading audit records...
                    </td>
                  </tr>
                ) : logs.length === 0 ? (
                  <tr>
                    <td colSpan={6} className="px-6 py-8 text-center text-gray-400">
                      No administrative events recorded yet.
                    </td>
                  </tr>
                ) : (
                  logs.map((log) => (
                    <tr key={log.id} className="hover:bg-gray-50/50">
                      <td className="whitespace-nowrap px-6 py-4 font-mono text-gray-500">
                        {new Date(log.created_at).toLocaleString()}
                      </td>
                      <td className="whitespace-nowrap px-6 py-4">
                        <span className="rounded bg-blue-50 px-2 py-0.5 font-semibold text-blue-700">
                          {log.action}
                        </span>
                      </td>
                      <td className="whitespace-nowrap px-6 py-4">
                        <span className="rounded bg-gray-100 px-2 py-0.5 font-medium text-gray-700">
                          {log.target_type}
                        </span>
                      </td>
                      <td className="whitespace-nowrap px-6 py-4">
                        <span className="font-semibold text-gray-800">
                          {log.actor?.full_name || "System"}
                        </span>
                        {log.actor?.email && (
                          <div className="text-[10px] text-gray-400">
                            {log.actor.email}
                          </div>
                        )}
                      </td>
                      <td className="whitespace-nowrap px-6 py-4 text-gray-400 font-mono text-[11px]">
                        {log.ip_address || "—"}
                      </td>
                      <td className="px-6 py-4 font-mono text-[11px] text-gray-600 max-w-xs truncate">
                        {log.payload ? JSON.stringify(log.payload) : "—"}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
};
