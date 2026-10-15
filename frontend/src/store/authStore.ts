/**
 * Zustand in-memory authentication store.
 *
 * CRITICAL SECURITY INVARIANT:
 * Access tokens are stored ONLY in memory and MUST NEVER be written
 * to localStorage, sessionStorage, or IndexedDB.
 */

import { create } from "zustand";
import {
  apiClient,
  clearPendingOperation,
  configureAuthStoreHooks,
  notifyLogout,
  refreshAccessTokenCoordinated,
  setSessionId,
  startNewSession,
} from "../api/client";

export interface UserBrief {
  id: string;
  email: string;
  full_name: string;
  avatar_url?: string | null;
}

export interface UserMeOrganization {
  id: string;
  name: string;
  slug: string;
  role: string;
}

export interface UserMeProfile extends UserBrief {
  organizations: UserMeOrganization[];
}

interface AuthState {
  user: UserBrief | null;
  organizations: UserMeOrganization[];
  currentOrganization: UserMeOrganization | null;
  accessToken: string | null;
  isAuthenticated: boolean;
  isLoading: boolean;

  setAuth: (user: UserBrief, accessToken: string) => void;
  setAccessToken: (token: string | null) => void;
  setOrganizations: (orgs: UserMeOrganization[]) => void;
  setCurrentOrganization: (org: UserMeOrganization | null) => void;
  initializeAuth: () => Promise<void>;
  fetchMe: () => Promise<UserMeProfile | null>;
  logout: () => Promise<void>;
  reset: () => void;
}

let initAuthPromise: Promise<void> | null = null;

export const useAuthStore = create<AuthState>((set, get) => ({
  user: null,
  organizations: [],
  currentOrganization: null,
  accessToken: null,
  isAuthenticated: false,
  isLoading: true,

  setAuth: (user, accessToken) => {
    startNewSession();
    set({
      user,
      accessToken,
      isAuthenticated: true,
      isLoading: false,
    });
  },

  setAccessToken: (accessToken) => {
    set((state) => ({
      accessToken,
      isAuthenticated: !!accessToken || state.isAuthenticated,
    }));
  },

  setOrganizations: (organizations) => {
    const current = get().currentOrganization;
    let selected: UserMeOrganization | null = current;
    if (!selected && organizations.length > 0) {
      selected = organizations[0];
    } else if (selected) {
      const selectedId = selected.id;
      if (!organizations.some((o) => o.id === selectedId)) {
        selected = organizations[0] || null;
      }
    }
    set({ organizations, currentOrganization: selected });
  },

  setCurrentOrganization: (currentOrganization) => {
    set({ currentOrganization });
  },

  initializeAuth: async () => {
    if (initAuthPromise) {
      return initAuthPromise;
    }
    initAuthPromise = (async () => {
      try {
        set({ isLoading: true });
        await refreshAccessTokenCoordinated();
        await get().fetchMe();
      } catch {
        set({
          user: null,
          accessToken: null,
          isAuthenticated: false,
          isLoading: false,
        });
      } finally {
        set({ isLoading: false });
      }
    })();
    return initAuthPromise;
  },

  fetchMe: async () => {
    try {
      const profile = await apiClient<UserMeProfile>("/auth/me");
      set({
        user: {
          id: profile.id,
          email: profile.email,
          full_name: profile.full_name,
          avatar_url: profile.avatar_url,
        },
        organizations: profile.organizations,
        currentOrganization:
          get().currentOrganization ||
          (profile.organizations.length > 0 ? profile.organizations[0] : null),
        isAuthenticated: true,
        isLoading: false,
      });
      return profile;
    } catch {
      set({
        user: null,
        accessToken: null,
        isAuthenticated: false,
        isLoading: false,
      });
      return null;
    }
  },

  logout: async () => {
    initAuthPromise = null;
    notifyLogout();
    try {
      await fetch("/api/v1/auth/logout", {
        method: "POST",
        credentials: "include",
      });
    } catch {
      // Ignore network error on logout
    } finally {
      clearPendingOperation();
      get().reset();
    }
  },

  reset: () => {
    initAuthPromise = null;
    clearPendingOperation();
    setSessionId(null);
    set({
      user: null,
      organizations: [],
      currentOrganization: null,
      accessToken: null,
      isAuthenticated: false,
      isLoading: false,
    });
  },
}));

// Wire up global API client hooks
configureAuthStoreHooks(
  () => useAuthStore.getState().accessToken,
  (token) => useAuthStore.getState().setAccessToken(token),
  () => useAuthStore.getState().reset()
);
