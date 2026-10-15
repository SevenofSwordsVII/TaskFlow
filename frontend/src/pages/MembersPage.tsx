import React from "react";
import { Link } from "react-router-dom";
import { MemberList } from "../features/organizations/components/MemberList";

export const MembersPage: React.FC = () => {
  return (
    <div className="min-h-screen bg-gray-50 p-6 md:p-10">
      <div className="mx-auto max-w-5xl">
        <div className="mb-6">
          <Link
            to="/projects"
            className="text-xs font-semibold text-blue-600 hover:underline"
          >
            ← Back to Projects
          </Link>
        </div>
        <MemberList />
      </div>
    </div>
  );
};
