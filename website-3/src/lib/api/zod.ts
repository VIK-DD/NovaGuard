import { z, ZodError } from "zod";

// NovaGuard intentionally ships a strict CSP without `unsafe-eval`. Zod can
// generate optimized validators with Function(), and even its caught feature
// probe is reported as a CSP issue by Chromium. Jitless mode uses the normal
// interpreter, so validation stays functional without weakening the policy.
z.config({ jitless: true });

export { z, ZodError };
