import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "@tanstack/react-router";
import { ApiError } from "../lib/api/client";
import { router } from "./router";

// Codes where retrying can never help — the user has to act instead.
const NO_RETRY_CODES = ["unauthorized", "session_expired", "forbidden", "guild_not_found"];

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: (failureCount, error) => {
        if (error instanceof ApiError && NO_RETRY_CODES.includes(error.code)) return false;
        return failureCount < 2;
      },
    },
  },
});

createRoot(document.getElementById("app")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
);
