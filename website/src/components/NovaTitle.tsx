import { useEffect, useRef } from "react";

/**
 * The signature element: an extruded 3D wordmark that tilts toward the
 * pointer. Depth comes from a stacked text-shadow on the ::before layer;
 * the face carries the nova plasma gradient.
 */
export default function NovaTitle({ launched }: { launched: boolean }) {
  const tiltRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

    let frame = 0;
    const target = { x: 0, y: 0 };
    const current = { x: 0, y: 0 };

    const onPointer = (event: PointerEvent) => {
      const nx = event.clientX / window.innerWidth - 0.5;
      const ny = event.clientY / window.innerHeight - 0.5;
      target.x = ny * -13;
      target.y = nx * 17;
    };

    const tick = () => {
      current.x += (target.x - current.x) * 0.07;
      current.y += (target.y - current.y) * 0.07;
      if (tiltRef.current) {
        tiltRef.current.style.transform = `rotateX(${current.x.toFixed(2)}deg) rotateY(${current.y.toFixed(2)}deg)`;
      }
      frame = requestAnimationFrame(tick);
    };

    window.addEventListener("pointermove", onPointer);
    frame = requestAnimationFrame(tick);
    return () => {
      window.removeEventListener("pointermove", onPointer);
      cancelAnimationFrame(frame);
    };
  }, []);

  return (
    <div className="title-stage">
      <div className={`title-tilt${launched ? " is-live" : ""}`} ref={tiltRef}>
        <h1 className="nova-title" data-text="NOVAGUARD">
          NOVAGUARD
        </h1>
        <span className="title-sheen" aria-hidden="true" />
      </div>
    </div>
  );
}
