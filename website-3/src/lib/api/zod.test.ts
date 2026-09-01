// The site ships a CSP with no `unsafe-eval`, and zod builds faster validators
// with `new Function` unless `jitless` is set. Zod skips even its capability
// *probe* under that flag - which matters, because Chromium reports the probe
// as a blocked-eval issue in DevTools despite zod catching the throw. The user
// sees "Content Security Policy blocks the use of eval" and nothing works
// differently, which is the worst kind of report: alarming and unactionable.
//
// `src/lib/api/zod.ts` sets the flag at module scope, so it runs before any
// schema built on top of it. That ordering is the whole control, and nothing
// checked it. It breaks quietly in three ways: someone imports `zod` directly
// instead of the wrapper, someone moves the `z.config` call inside a function,
// or a zod upgrade evaluates the probe earlier.
//
// So this asserts the behaviour rather than the configuration: with the global
// `Function` replaced by one that throws - which is what a CSP without
// unsafe-eval does - parsing must still succeed and must never have reached
// for it.
import { afterEach, describe, expect, it, vi } from "vitest";

import { z, ZodError } from "./zod";

describe("CSP-safe Zod configuration", () => {
  it("keeps JIT disabled globally while preserving validation", () => {
    expect(z.config().jitless).toBe(true);

    const schema = z.object({ ready: z.boolean() });
    expect(schema.parse({ ready: true })).toEqual({ ready: true });
    expect(() => schema.parse({ ready: "yes" })).toThrow(ZodError);
  });
});

const RealFunction = globalThis.Function;

afterEach(() => {
  globalThis.Function = RealFunction;
  vi.resetModules();
});

/** Stand in for a CSP that refuses string evaluation, and record attempts. */
function blockStringEvaluation() {
  const attempts: unknown[][] = [];
  const blocked = new Proxy(RealFunction, {
    apply(_target, _thisArg, args) {
      attempts.push(args);
      throw new EvalError("blocked by Content Security Policy");
    },
    construct(_target, args) {
      attempts.push(args);
      throw new EvalError("blocked by Content Security Policy");
    },
  });
  globalThis.Function = blocked as FunctionConstructor;
  return attempts;
}

describe("zod under a CSP without unsafe-eval", () => {
  it("parses a real payload without reaching for Function()", async () => {
    const attempts = blockStringEvaluation();

    // Imported *after* the global is replaced, so the module's own top-level
    // `z.config({ jitless: true })` runs inside the restriction rather than
    // before it - the same order a browser loads it in.
    vi.resetModules();
    const { GuildSchema } = await import("./schemas");

    const parsed = GuildSchema.parse({
      id: "123456789012345678",
      name: "NovaGuard HQ",
      icon: null,
      owner: true,
      permissions: 8,
      bot_present: true,
    });

    expect(parsed.name).toBe("NovaGuard HQ");
    expect(attempts).toEqual([]);
  });

  it("reports a validation failure normally, still without Function()", async () => {
    // The failure path builds error objects and messages, which is where a
    // jitted formatter would be reached for if one existed.
    const attempts = blockStringEvaluation();

    vi.resetModules();
    const { GuildSchema } = await import("./schemas");

    expect(() => GuildSchema.parse({ id: 7 })).toThrow();
    expect(attempts).toEqual([]);
  });

  it("is reached through the wrapper, not around it", async () => {
    // The flag is applied by `lib/api/zod.ts` at import time, so a module that
    // imports `zod` directly gets an unconfigured copy and the probe comes
    // back. Nothing outside the wrapper and this test may import it.
    const sources = import.meta.glob("../../**/*.{ts,tsx}", {
      query: "?raw",
      import: "default",
      eager: true,
    }) as Record<string, string>;

    const offenders = Object.entries(sources)
      // The wrapper is where the import belongs, and test files never reach a
      // browser - only shipped modules can put the probe back on a page.
      .filter(([path]) => !/(?:^|\/)zod\.ts$/.test(path))
      .filter(([path]) => !/\.test\.tsx?$/.test(path))
      .filter(([, source]) => /from\s+["']zod["']/.test(source))
      .map(([path]) => path);

    expect(offenders).toEqual([]);
  });
});
