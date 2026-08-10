import { StrictMode } from "react";
import { QueryCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "@tanstack/react-router";
import { ZodError } from "zod";
import { ApiError } from "../lib/api/client";
import { router } from "./router";
import { UnsavedChangesProvider } from "./unsavedChanges";

// Codes where retrying can never help — the user has to act instead.
const NO_RETRY_CODES = ["unauthorized", "session_expired", "forbidden", "guild_not_found"];

const queryCache = new QueryCache({
  onError: (error, query) => {
    if (
      query.queryKey[0] !== "me" &&
      error instanceof ApiError &&
      (error.code === "unauthorized" || error.code === "session_expired")
    ) {
      void queryClient.invalidateQueries({ queryKey: ["me"] });
    }
  },
});

const queryClient = new QueryClient({
  queryCache,
  defaultOptions: {
    queries: {
      staleTime: 2 * 60_000,
      gcTime: 5 * 60_000,
      refetchOnWindowFocus: false,
      retry: (failureCount, error) => {
        if (error instanceof ApiError && NO_RETRY_CODES.includes(error.code)) return false;
        if (error instanceof ZodError) return false;
        return failureCount < 2;
      },
    },
  },
});

// Mounted as an Astro `client:only="react"` island (see pages/dashboard/index.astro).
// Rendering through the island — rather than a hand-rolled createRoot script — is
// what makes Astro inject @vitejs/plugin-react's HMR preamble in dev; without it
// every dashboard module throws "can't detect preamble" and nothing renders.
export default function App() {
  return (
    <StrictMode>
      <UnsavedChangesProvider>
        <QueryClientProvider client={queryClient}>
          <RouterProvider router={router} />
        </QueryClientProvider>
      </UnsavedChangesProvider>
    </StrictMode>
  );
}
