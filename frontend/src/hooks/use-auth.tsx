import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";

import { api, getAccessToken, setAccessToken, setOnUnauthorized } from "@/api/client";
import type { User } from "@/types";

interface AuthState {
  user: User | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  refreshUser: () => Promise<void>;
  hasRole: (...roles: string[]) => boolean;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  const refreshUser = useCallback(async () => {
    try {
      const res = await api.get<User>("/auth/me");
      setUser(res.data);
    } catch {
      setUser(null);
    }
  }, []);

  useEffect(() => {
    setOnUnauthorized(() => {
      setAccessToken(null);
      setUser(null);
    });
    // Restore the session on first load. The access token was rehydrated from
    // localStorage at import, so validate it via /auth/me; if it's
    // missing/expired the api client transparently falls back to the refresh
    // cookie (401 -> POST /auth/refresh -> retry). Either path keeps the user
    // logged in across a refresh; only a genuine failure clears state.
    (async () => {
      try {
        if (getAccessToken()) {
          await refreshUser();
        } else {
          const res = await api.post<{ access_token: string }>("/auth/refresh");
          setAccessToken(res.data.access_token);
          await refreshUser();
        }
      } catch {
        setUser(null);
      } finally {
        setLoading(false);
      }
    })();
  }, [refreshUser]);

  const login = useCallback(
    async (email: string, password: string) => {
      const res = await api.post<{ access_token: string }>("/auth/login", {
        email,
        password,
      });
      setAccessToken(res.data.access_token);
      await refreshUser();
    },
    [refreshUser],
  );

  const logout = useCallback(async () => {
    try {
      await api.post("/auth/logout");
    } finally {
      setAccessToken(null);
      setUser(null);
    }
  }, []);

  const hasRole = useCallback(
    (...roles: string[]) => (user ? roles.includes(user.role) : false),
    [user],
  );

  return (
    <AuthContext.Provider
      value={{ user, loading, login, logout, refreshUser, hasRole }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
