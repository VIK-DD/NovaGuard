import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { NumberField, Section, Toggle } from "./ConfigPrimitives";

afterEach(cleanup);

describe("Toggle", () => {
  it("exposes switch semantics and requests the opposite state", () => {
    const onChange = vi.fn();
    render(<Toggle label="Enable AutoMod" checked={false} onChange={onChange} />);

    const control = screen.getByRole("switch", { name: "Enable AutoMod" });
    expect(control).toHaveAttribute("aria-checked", "false");
    fireEvent.click(control);
    expect(onChange).toHaveBeenCalledOnce();
    expect(onChange).toHaveBeenCalledWith(true);
  });
});

describe("NumberField", () => {
  it("keeps the label, bounds and validation relationship accessible", () => {
    render(
      <NumberField
        label="Cooldown"
        suffix="seconds"
        value={60}
        min={0}
        max={3600}
        error="Use a whole number"
        onChange={() => undefined}
      />,
    );

    const input = screen.getByRole("spinbutton", { name: "Cooldown (seconds)" });
    expect(input).toHaveAttribute("min", "0");
    expect(input).toHaveAttribute("max", "3600");
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(input).toHaveAccessibleDescription("Use a whole number");
  });

  it("allows temporary empty text and emits only whole numbers", () => {
    const onChange = vi.fn();
    render(
      <NumberField label="Winners" value={1} min={1} max={20} onChange={onChange} />,
    );

    const input = screen.getByRole("spinbutton", { name: "Winners" });
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: "" } });
    expect(onChange).not.toHaveBeenCalled();
    fireEvent.change(input, { target: { value: "12" } });
    expect(onChange).toHaveBeenCalledWith(12);
  });
});

describe("Section", () => {
  it("connects its heading and renders the configured state", () => {
    const { container } = render(
      <Section
        id="moderation"
        icon="shield-check"
        kicker="Moderation"
        description="Protect the server."
        active={true}
      >
        <p>Controls</p>
      </Section>,
    );

    const section = container.querySelector("section");
    expect(section).toHaveAttribute("aria-labelledby", "moderation-title");
    expect(screen.getByText("Active")).toBeInTheDocument();
    expect(screen.getByText("Controls")).toBeInTheDocument();
  });
});
