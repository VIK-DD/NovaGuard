import { useEffect, useRef } from "react";
import type { Theme } from "../App";

type Star = { x: number; y: number; z: number; r: number; phase: number; tint: number };
type Meteor = { x: number; y: number; vx: number; vy: number; life: number } | null;

const STAR_COUNT = 170;
const TINTS_DARK = ["236, 233, 247", "255, 77, 157", "255, 180, 84"];
const TINTS_LIGHT = ["59, 48, 110", "199, 44, 122", "196, 120, 24"];

export default function Starfield({ theme }: { theme: Theme }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const themeRef = useRef(theme);
  themeRef.current = theme;

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let width = 0;
    let height = 0;
    let frame = 0;
    let meteor: Meteor = null;
    let nextMeteorAt = performance.now() + 4000 + Math.random() * 6000;
    const pointer = { x: 0, y: 0 };
    const eased = { x: 0, y: 0 };

    const stars: Star[] = Array.from({ length: STAR_COUNT }, () => ({
      x: Math.random(),
      y: Math.random(),
      z: 0.25 + Math.random() * 0.75,
      r: 0.4 + Math.random() * 1.1,
      phase: Math.random() * Math.PI * 2,
      // ~1 in 8 stars glows pink or amber — nova sparks in the field
      tint: Math.random() < 0.125 ? 1 + Math.floor(Math.random() * 2) : 0,
    }));

    const resize = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      width = window.innerWidth;
      height = window.innerHeight;
      canvas.width = width * dpr;
      canvas.height = height * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };

    const onPointer = (event: PointerEvent) => {
      pointer.x = event.clientX / width - 0.5;
      pointer.y = event.clientY / height - 0.5;
    };

    const draw = (now: number) => {
      ctx.clearRect(0, 0, width, height);
      const tints = themeRef.current === "dark" ? TINTS_DARK : TINTS_LIGHT;
      const baseAlpha = themeRef.current === "dark" ? 1 : 0.55;

      eased.x += (pointer.x - eased.x) * 0.04;
      eased.y += (pointer.y - eased.y) * 0.04;

      for (const star of stars) {
        const twinkle = reduced ? 0.75 : 0.4 + 0.6 * Math.abs(Math.sin(now / 1400 + star.phase));
        const px = star.x * width - eased.x * star.z * 26;
        const py = star.y * height - eased.y * star.z * 26;
        ctx.beginPath();
        ctx.arc(px, py, star.r * star.z, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(${tints[star.tint]}, ${(twinkle * baseAlpha).toFixed(3)})`;
        ctx.fill();
      }

      if (!reduced) {
        if (!meteor && now >= nextMeteorAt) {
          meteor = {
            x: width * (0.1 + Math.random() * 0.6),
            y: height * Math.random() * 0.35,
            vx: 6 + Math.random() * 5,
            vy: 2.2 + Math.random() * 1.6,
            life: 1,
          };
        }
        if (meteor) {
          const gradient = ctx.createLinearGradient(
            meteor.x,
            meteor.y,
            meteor.x - meteor.vx * 9,
            meteor.y - meteor.vy * 9,
          );
          gradient.addColorStop(0, `rgba(${tints[0]}, ${(0.9 * meteor.life * baseAlpha).toFixed(3)})`);
          gradient.addColorStop(1, `rgba(${tints[0]}, 0)`);
          ctx.strokeStyle = gradient;
          ctx.lineWidth = 1.4;
          ctx.beginPath();
          ctx.moveTo(meteor.x, meteor.y);
          ctx.lineTo(meteor.x - meteor.vx * 9, meteor.y - meteor.vy * 9);
          ctx.stroke();

          meteor.x += meteor.vx;
          meteor.y += meteor.vy;
          meteor.life -= 0.016;
          if (meteor.life <= 0 || meteor.x > width + 120 || meteor.y > height + 120) {
            meteor = null;
            nextMeteorAt = now + 5000 + Math.random() * 8000;
          }
        }
      }

      frame = requestAnimationFrame(draw);
    };

    resize();
    window.addEventListener("resize", resize);
    window.addEventListener("pointermove", onPointer);
    frame = requestAnimationFrame(draw);

    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("resize", resize);
      window.removeEventListener("pointermove", onPointer);
    };
  }, []);

  return <canvas ref={canvasRef} className="starfield" aria-hidden="true" />;
}
