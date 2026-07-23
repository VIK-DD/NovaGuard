import { StrictMode } from "react";
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

// Mounted as an Astro `client:only="react"` island (see pages/dashboard/index.astro).
// Rendering through the island — rather than a hand-rolled createRoot script — is
// what makes Astro inject @vitejs/plugin-react's HMR preamble in dev; without it
// every dashboard module throws "can't detect preamble" and nothing renders.
export default function App() {
  return (
    <StrictMode>
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
      </QueryClientProvider>
    </StrictMode>
  );
}
