import React, { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useAuthStore } from "../../../store/authStore";
import { apiClient } from "../../../api/client";
import { InviteMemberModal } from "./InviteMemberModal";

interface Member {
  id: string;
  organization_id: string;
  user_id: string;
  role: "OWNER" | "ADMIN" | "MEMBER" | "VIEWER";
  created_at: string;
  user?: {
    id: string;
    email: string;
    full_name: string;
  };
}

interface Invitation {
  id: string;
  organization_id: string;
  email: string;
  role: string;
  expires_at: string;
  created_at: string;
}

export const MemberList: React.FC = () => {
  const queryClient = useQueryClient();
  const { currentOrganization, user: currentUser } = useAuthStore();
  const [isInviteModalOpen, setIsInviteModalOpen] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const orgId = currentOrganization?.id;
  const callerRole = currentOrganization?.role;
  const isCallerAdmin = callerRole === "OWNER" || callerRole === "ADMIN";

  const { data: members = [], isLoading: membersLoading } = useQuery<Member[]>({
    queryKey: ["orgMembers", orgId],
    queryFn: async () => {
      const res = await apiClient<{ items: Member[] }>(
        `/organizations/${orgId}/members`
      );
      return res.items || [];
    },
    enabled: !!orgId,
  });

  const { data: invitations = [], isLoading: invsLoading } = useQuery<Invitation[]>({
    queryKey: ["orgInvitations", orgId],
    queryFn: () => apiClient<Invitation[]>(`/organizations/${orgId}/invitations`),
    enabled: !!orgId && isCallerAdmin,
  });

  const updateRoleMutation = useMutation({
    mutationFn: ({ userId, role }: { userId: string; role: string }) =>
      apiClient<Member>(`/organizations/${orgId}/members/${userId}`, {
        method: "PATCH",
        body: JSON.stringify({ role }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["orgMembers", orgId] });
      setErrorMsg(null);
    },
    onError: (err: Error) => {
      setErrorMsg(err.message || "Failed to update member role");
    },
  });

  const removeMemberMutation = useMutation({
    mutationFn: (userId: string) =>
      apiClient(`/organizations/${orgId}/members/${userId}`, {
        method: "DELETE",
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["orgMembers", orgId] });
      setErrorMsg(null);
    },
    onError: (err: Error) => {
      setErrorMsg(err.message || "Failed to remove member");
    },
  });

  const revokeInvitationMutation = useMutation({
    mutationFn: (invId: string) =>
      apiClient(`/organizations/${orgId}/invitations/${invId}`, {
        method: "DELETE",
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["orgInvitations", orgId] });
    },
  });

  if (!currentOrganization) {
    return <div className="p-8 text-gray-500">No active organization selected.</div>;
  }

  return (
    <div className="space-y-8">
      {/* Header */}
      <div className="flex flex-col items-start justify-between gap-4 sm:flex-row sm:items-center">
        <div>
          <h2 className="text-xl font-bold text-gray-900">Workspace Members</h2>
          <p className="mt-1 text-sm text-gray-500">
            Manage who has access to {currentOrganization.name} and their authorization levels.
          </p>
        </div>
        {isCallerAdmin && (
          <button
            onClick={() => setIsInviteModalOpen(true)}
            className="rounded bg-blue-600 px-4 py-2 text-sm font-semibold text-white shadow hover:bg-blue-700"
          >
            + Invite Member
          </button>
        )}
      </div>

      {errorMsg && (
        <div className="rounded bg-red-50 p-4 text-sm text-red-700">
          {errorMsg}
        </div>
      )}

      {/* Active Members Table */}
      <div className="overflow-hidden rounded-xl border border-gray-200 bg-white shadow-sm">
        <div className="border-b border-gray-200 bg-gray-50/50 px-6 py-4">
          <h3 className="font-semibold text-gray-900">Active Members ({members.length})</h3>
        </div>
        <div className="divide-y divide-gray-100">
          {membersLoading ? (
            <div className="p-6 text-center text-sm text-gray-500">Loading members...</div>
          ) : members.length === 0 ? (
            <div className="p-6 text-center text-sm text-gray-500">No members found.</div>
          ) : (
            members.map((m) => {
              const isSelf = m.user_id === currentUser?.id;
              const isOwner = m.role === "OWNER";
              const canModify =
                isCallerAdmin &&
                !isOwner &&
                (!isSelf || callerRole === "OWNER") &&
                (callerRole === "OWNER" || m.role !== "ADMIN");

              return (
                <div
                  key={m.id}
                  className="flex flex-col justify-between gap-3 p-6 sm:flex-row sm:items-center"
                >
                  <div className="flex items-center gap-3">
                    <div className="flex h-10 w-10 items-center justify-center rounded-full bg-blue-600 font-bold text-white">
                      {(m.user?.full_name || "U")[0].toUpperCase()}
                    </div>
                    <div>
                      <p className="font-semibold text-gray-900">
                        {m.user?.full_name || "Unknown"}
                        {isSelf && (
                          <span className="ml-2 text-xs font-normal text-gray-400">
                            (you)
                          </span>
                        )}
                      </p>
                      <p className="text-xs text-gray-500">{m.user?.email}</p>
                    </div>
                  </div>

                  <div className="flex items-center gap-4">
                    {canModify ? (
                      <select
                        value={m.role}
                        onChange={(e) =>
                          updateRoleMutation.mutate({
                            userId: m.user_id,
                            role: e.target.value,
                          })
                        }
                        className="rounded border border-gray-300 px-2.5 py-1 text-xs font-semibold focus:border-blue-500 focus:outline-none"
                      >
                        <option value="ADMIN">ADMIN</option>
                        <option value="MEMBER">MEMBER</option>
                        <option value="VIEWER">VIEWER</option>
                      </select>
                    ) : (
                      <span
                        className={`rounded px-2.5 py-1 text-xs font-bold ${
                          isOwner
                            ? "bg-purple-100 text-purple-800"
                            : m.role === "ADMIN"
                            ? "bg-blue-100 text-blue-800"
                            : m.role === "MEMBER"
                            ? "bg-emerald-100 text-emerald-800"
                            : "bg-gray-100 text-gray-700"
                        }`}
                      >
                        {m.role}
                      </span>
                    )}

                    {canModify && (
                      <button
                        onClick={() => {
                          if (
                            window.confirm(
                              `Remove ${m.user?.full_name || "user"} from organization? Their assigned tasks will become unassigned.`
                            )
                          ) {
                            removeMemberMutation.mutate(m.user_id);
                          }
                        }}
                        className="text-xs font-medium text-red-600 hover:underline"
                      >
                        Remove
                      </button>
                    )}
                  </div>
                </div>
              );
            })
          )}
        </div>
      </div>

      {/* Pending Invitations Table */}
      {isCallerAdmin && (
        <div className="overflow-hidden rounded-xl border border-gray-200 bg-white shadow-sm">
          <div className="border-b border-gray-200 bg-gray-50/50 px-6 py-4">
            <h3 className="font-semibold text-gray-900">
              Pending Invitations ({invitations.length})
            </h3>
          </div>
          <div className="divide-y divide-gray-100">
            {invsLoading ? (
              <div className="p-6 text-center text-sm text-gray-500">Loading invitations...</div>
            ) : invitations.length === 0 ? (
              <div className="p-6 text-center text-sm text-gray-500">
                No active invitations pending.
              </div>
            ) : (
              invitations.map((inv) => (
                <div
                  key={inv.id}
                  className="flex items-center justify-between p-6"
                >
                  <div>
                    <p className="font-semibold text-gray-900">{inv.email}</p>
                    <p className="text-xs text-gray-400">
                      Expires: {new Date(inv.expires_at).toLocaleDateString()}
                    </p>
                  </div>
                  <div className="flex items-center gap-3">
                    <span className="rounded bg-amber-100 px-2 py-0.5 text-xs font-semibold text-amber-800">
                      Role: {inv.role}
                    </span>
                    <button
                      onClick={() => revokeInvitationMutation.mutate(inv.id)}
                      className="text-xs text-red-600 hover:underline"
                    >
                      Revoke
                    </button>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
      )}

      {/* Invite Modal */}
      <InviteMemberModal
        isOpen={isInviteModalOpen}
        onClose={() => setIsInviteModalOpen(false)}
        organizationId={currentOrganization.id}
      />
    </div>
  );
};
