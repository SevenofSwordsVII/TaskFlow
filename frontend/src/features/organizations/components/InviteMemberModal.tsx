import React, { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "../../../api/client";

interface InviteMemberModalProps {
  isOpen: boolean;
  onClose: () => void;
  organizationId: string;
  onInvited?: () => void;
}

interface InvitationResponse {
  id: string;
  email: string;
  role: string;
  expires_at: string;
  invitation_token?: string;
}

export const InviteMemberModal: React.FC<InviteMemberModalProps> = ({
  isOpen,
  onClose,
  organizationId,
  onInvited,
}) => {
  const queryClient = useQueryClient();
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<"ADMIN" | "MEMBER" | "VIEWER">("MEMBER");
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [inviteToken, setInviteToken] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const inviteMutation = useMutation({
    mutationFn: (payload: { email: string; role: string }) =>
      apiClient<InvitationResponse>(`/organizations/${organizationId}/invitations`, {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ["orgInvitations", organizationId] });
      if (data.invitation_token) {
        setInviteToken(data.invitation_token);
      } else {
        handleClose();
      }
      onInvited?.();
    },
    onError: (err: Error) => {
      setErrorMsg(err.message || "Failed to send invitation");
    },
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setErrorMsg(null);
    inviteMutation.mutate({ email: email.trim(), role });
  };

  const handleClose = () => {
    setEmail("");
    setRole("MEMBER");
    setErrorMsg(null);
    setInviteToken(null);
    setCopied(false);
    onClose();
  };

  const copyToken = () => {
    if (inviteToken) {
      navigator.clipboard.writeText(inviteToken);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="w-full max-w-md rounded-xl bg-white p-6 shadow-xl">
        <h2 className="text-xl font-bold text-gray-900">Invite Team Member</h2>
        <p className="mt-1 text-sm text-gray-500">
          Send an invitation to join your workspace with role-based permissions.
        </p>

        {errorMsg && (
          <div className="mt-4 rounded bg-red-50 p-3 text-sm text-red-700">
            {errorMsg}
          </div>
        )}

        {inviteToken ? (
          <div className="mt-5 space-y-4">
            <div className="rounded bg-emerald-50 p-4 border border-emerald-200">
              <p className="text-sm font-semibold text-emerald-900">
                Invitation Created Successfully!
              </p>
              <p className="mt-1 text-xs text-emerald-700">
                Share this invitation token with <strong>{email}</strong>:
              </p>
              <div className="mt-3 flex items-center gap-2">
                <input
                  type="text"
                  readOnly
                  value={inviteToken}
                  className="w-full rounded border border-emerald-300 bg-white p-2 font-mono text-xs text-gray-800"
                />
                <button
                  type="button"
                  onClick={copyToken}
                  className="rounded bg-emerald-600 px-3 py-2 text-xs font-semibold text-white shadow hover:bg-emerald-700"
                >
                  {copied ? "Copied!" : "Copy"}
                </button>
              </div>
            </div>

            <div className="flex justify-end pt-2">
              <button
                type="button"
                onClick={handleClose}
                className="rounded bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700"
              >
                Done
              </button>
            </div>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="mt-5 space-y-4">
            <div>
              <label className="block text-xs font-semibold uppercase text-gray-600">
                Email Address
              </label>
              <input
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="colleague@example.com"
                className="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
              />
            </div>

            <div>
              <label className="block text-xs font-semibold uppercase text-gray-600">
                Workspace Role
              </label>
              <select
                value={role}
                onChange={(e) =>
                  setRole(e.target.value as "ADMIN" | "MEMBER" | "VIEWER")
                }
                className="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
              >
                <option value="MEMBER">Member (Can edit tasks and create boards)</option>
                <option value="ADMIN">Admin (Can manage projects and members)</option>
                <option value="VIEWER">Viewer (Read-only access)</option>
              </select>
            </div>

            <div className="mt-6 flex justify-end gap-3 pt-2">
              <button
                type="button"
                onClick={handleClose}
                className="rounded px-4 py-2 text-sm font-medium text-gray-600 hover:bg-gray-100"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={inviteMutation.isPending}
                className="rounded bg-blue-600 px-4 py-2 text-sm font-semibold text-white shadow hover:bg-blue-700 disabled:opacity-50"
              >
                {inviteMutation.isPending ? "Inviting..." : "Send Invitation"}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
};
