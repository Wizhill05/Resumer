"use client";
import { createContext, useContext, useState, useEffect, ReactNode } from "react";
import { api } from "@/lib/api";
import type { User } from "@/lib/types";

interface UserContextValue {
  users: User[];
  activeUser: User | null;
  setActiveUser: (user: User) => void;
  createUser: (name: string) => Promise<void>;
  loading: boolean;
  refresh: () => Promise<void>;
}

const UserContext = createContext<UserContextValue | null>(null);

export function UserProvider({ children }: { children: ReactNode }) {
  const [users, setUsers] = useState<User[]>([]);
  const [activeUser, setActiveUserState] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = async () => {
    const list = await api.listUsers();
    setUsers(list);
    if (list.length > 0) {
      setActiveUserState(list[0]);
    }
  };

  useEffect(() => {
    refresh().finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // No-ops for backward compat
  const setActiveUser = (_user: User) => {};
  const createUser = async (_name: string) => {};

  return (
    <UserContext.Provider value={{ users, activeUser, setActiveUser, createUser, loading, refresh }}>
      {children}
    </UserContext.Provider>
  );
}

export function useUser() {
  const ctx = useContext(UserContext);
  if (!ctx) throw new Error("useUser must be inside UserProvider");
  return ctx;
}
