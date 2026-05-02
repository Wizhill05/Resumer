"use client";
import { useState } from "react";
import { useUser } from "@/lib/user-context";

export default function Header() {
  const { users, activeUser, setActiveUser, createUser } = useUser();
  const [newName, setNewName] = useState("");
  const [creating, setCreating] = useState(false);
  const [showCreate, setShowCreate] = useState(false);

  const handleCreate = async () => {
    if (!newName.trim()) return;
    setCreating(true);
    try {
      await createUser(newName.trim());
      setNewName("");
      setShowCreate(false);
    } finally {
      setCreating(false);
    }
  };

  return (
    <header className="h-10 flex items-center justify-between px-4 bg-neutral-900 border-b border-neutral-800 flex-shrink-0">
      <span className="text-xs text-neutral-500">Local Dashboard</span>
      <div className="flex items-center gap-2">
        <span className="text-xs text-neutral-500">Profile:</span>
        <select
          className="text-xs bg-neutral-800 border border-neutral-700 text-neutral-100 rounded px-2 py-0.5 cursor-pointer"
          value={activeUser?.id ?? ""}
          onChange={(e) => {
            const u = users.find((u) => u.id === e.target.value);
            if (u) setActiveUser(u);
          }}
        >
          {users.map((u) => (
            <option key={u.id} value={u.id}>{u.display_name}</option>
          ))}
        </select>
        {showCreate ? (
          <div className="flex items-center gap-1">
            <input
              className="text-xs bg-neutral-800 border border-neutral-700 text-neutral-100 rounded px-2 py-0.5 w-28"
              placeholder="Profile name"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleCreate()}
              autoFocus
            />
            <button
              className="text-xs px-2 py-0.5 bg-blue-700 text-white rounded disabled:opacity-50"
              onClick={handleCreate}
              disabled={creating}
            >
              {creating ? "…" : "Add"}
            </button>
            <button
              className="text-xs px-2 py-0.5 bg-neutral-700 text-neutral-300 rounded"
              onClick={() => setShowCreate(false)}
            >
              ✕
            </button>
          </div>
        ) : (
          <button
            className="text-xs px-2 py-0.5 bg-neutral-800 border border-neutral-700 text-neutral-300 rounded hover:bg-neutral-700"
            onClick={() => setShowCreate(true)}
          >
            + New
          </button>
        )}
      </div>
    </header>
  );
}
