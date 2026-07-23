import { useRef } from "react";
import {
  motion,
  useMotionValue,
  useReducedMotion,
  useSpring,
  useTransform,
  type TargetAndTransition,
} from "motion/react";

// The hero's product proof: a floating Discord embed (what NovaGuard actually
// posts) layered with a sliver of the dashboard (how you configure it).
// Mouse-tracked parallax with spring physics — not a static illustration.
// All motion is disabled under prefers-reduced-motion (also saves battery /
// stops the perpetual float rAF on phones).

function useTilt(strength: number, enabled: boolean) {
  const ref = useRef<HTMLDivElement>(null);
  const mx = useMotionValue(0);
  const my = useMotionValue(0);
  const rx = useSpring(useTransform(my, [-0.5, 0.5], [strength, -strength]), {
    stiffness: 220,
    damping: 22,
  });
  const ry = useSpring(useTransform(mx, [-0.5, 0.5], [-strength, strength]), {
    stiffness: 220,
    damping: 22,
  });

  const onMouseMove = (e: React.MouseEvent<HTMLDivElement>) => {
    if (!enabled) return;
    const rect = ref.current?.getBoundingClientRect();
    if (!rect) return;
    mx.set((e.clientX - rect.left) / rect.width - 0.5);
    my.set((e.clientY - rect.top) / rect.height - 0.5);
  };
  const onMouseLeave = () => {
    mx.set(0);
    my.set(0);
  };

  return { ref, rx, ry, onMouseMove, onMouseLeave };
}

export default function HeroVisual() {
  const reduce = useReducedMotion() ?? false;
  const { ref, rx, ry, onMouseMove, onMouseLeave } = useTilt(8, !reduce);

  // Perpetual ambient float — skipped entirely when motion is reduced.
  const floatA: TargetAndTransition = reduce
    ? {}
    : { y: [0, -7, 0], transition: { y: { duration: 7, repeat: Infinity, ease: "easeInOut", delay: 1 } } };
  const floatB: TargetAndTransition = reduce
    ? {}
    : { y: [0, -9, 0], transition: { y: { duration: 6, repeat: Infinity, ease: "easeInOut", delay: 0.7 } } };

  return (
    <div
      ref={ref}
      onMouseMove={onMouseMove}
      onMouseLeave={onMouseLeave}
      style={{ perspective: 1400 }}
      className="relative mx-auto h-[380px] w-full max-w-md select-none sm:h-[420px]"
    >
      {/* Dashboard sliver — sits behind, upper-left */}
      <motion.div
        style={{ rotateX: rx, rotateY: ry, transformStyle: "preserve-3d" }}
        initial={{ opacity: 0, y: 20, x: -8 }}
        animate={{ opacity: 1, x: 0, ...floatA }}
        transition={{ opacity: { duration: 0.6, delay: 0.4 }, x: { duration: 0.6, delay: 0.4 } }}
        className="absolute top-2 left-0 w-[270px] -rotate-6 rounded-xl border border-line bg-card p-3.5"
      >
        <div className="flex items-center justify-between border-b border-line pb-2">
          <span className="flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-full bg-[#ff5f57]" />
            <span className="h-2 w-2 rounded-full bg-[#febc2e]" />
            <span className="h-2 w-2 rounded-full bg-[#28c840]" />
          </span>
          <span className="font-mono text-[9px] text-ink-faint">novaguard.fun/dashboard</span>
        </div>
        <div className="mt-2.5 space-y-2">
          <div>
            <p className="text-[9px] tracking-[0.14em] text-ink-faint uppercase">Welcome channel</p>
            <div className="mt-1 flex items-center justify-between rounded-md border border-line-strong bg-bg-subtle px-2 py-1.5 text-[11px]">
              <span># welcome</span>
              <span className="text-ink-faint">▾</span>
            </div>
          </div>
          <div className="flex items-center justify-between rounded-md border border-line-strong bg-bg-subtle px-2 py-1.5">
            <span className="text-[11px]">Block invites</span>
            <span className="relative h-[16px] w-[28px] rounded-full bg-primary">
              <span className="absolute top-[2px] right-[2px] h-[12px] w-[12px] rounded-full bg-[hsl(20_45%_8%)]" />
            </span>
          </div>
        </div>
      </motion.div>

      {/* Discord embed — the real product proof */}
      <motion.div
        style={{ rotateX: rx, rotateY: ry, transformStyle: "preserve-3d" }}
        initial={{ opacity: 0, y: 26, scale: 0.98 }}
        animate={{ opacity: 1, scale: 1, ...floatB }}
        transition={{ opacity: { duration: 0.6, delay: 0.1 }, scale: { duration: 0.6, delay: 0.1 } }}
        className="absolute right-0 bottom-6 w-[290px] rotate-2 rounded-xl border border-line bg-[hsl(220_7%_10%)] p-4 sm:right-2"
      >
        <div className="flex items-center gap-2.5">
          <div className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-primary font-display text-xs font-bold text-primary-ink">
            N
          </div>
          <div>
            <span className="flex items-center gap-1.5 text-[13px] font-medium text-white">
              NovaGuard
              <span className="rounded bg-primary px-1 py-[1px] text-[8px] font-semibold tracking-wide text-primary-ink uppercase">
                Bot
              </span>
            </span>
            <span className="text-[10px] text-white/40">Today at 9:41 PM</span>
          </div>
        </div>
        <div className="mt-2.5 rounded border-l-4 border-primary bg-white/5 py-2 pr-2.5 pl-3">
          <p className="text-[12.5px] font-semibold text-white">Welcome to the server, Mira!</p>
          <p className="mt-1 text-[11.5px] leading-relaxed text-white/55">
            You're member <span className="font-medium text-white/80">#248</span>. Check{" "}
            <span className="text-primary">#rules</span> to get started.
          </p>
        </div>
      </motion.div>
    </div>
  );
}
