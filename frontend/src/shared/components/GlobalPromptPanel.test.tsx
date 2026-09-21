// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const expandGlobalPrompt = vi.hoisted(() => vi.fn());
const getGlobalDirection = vi.hoisted(() => vi.fn());
const saveGlobalDirection = vi.hoisted(() => vi.fn());

vi.mock("../../features/director/api", () => ({
  expandGlobalPrompt,
  getGlobalDirection,
  saveGlobalDirection,
}));

import { GlobalPromptPanel } from "./GlobalPromptPanel";

describe("GlobalPromptPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getGlobalDirection.mockResolvedValue({ detail: "", negative: "" });
    expandGlobalPrompt.mockResolvedValue("详细细节：结构、材质、颜色、环境、光线。");
    saveGlobalDirection.mockResolvedValue({
      detail: "详细细节：结构、材质、颜色、环境、光线。",
      negative: "glass windshield",
    });
  });

  afterEach(() => {
    cleanup();
  });

  it("loads, expands with 生成细节, then saves with 保存全局细节", async () => {
    render(<GlobalPromptPanel />);

    await waitFor(() => expect(getGlobalDirection).toHaveBeenCalled());

    const saveButton = screen.getByRole("button", { name: "保存全局细节" });
    expect((saveButton as HTMLButtonElement).disabled).toBe(true);

    fireEvent.change(screen.getByPlaceholderText(/整体画面/), {
      target: { value: "雨夜老街的电影感画面" },
    });
    fireEvent.click(screen.getByRole("button", { name: "生成细节" }));

    await waitFor(() =>
      expect(screen.getByDisplayValue(/详细细节/)).toBeTruthy(),
    );
    expect(expandGlobalPrompt).toHaveBeenCalledWith("雨夜老街的电影感画面", "");

    fireEvent.change(screen.getByPlaceholderText(/glass windshield/), {
      target: { value: "glass windshield" },
    });

    await waitFor(() =>
      expect((saveButton as HTMLButtonElement).disabled).toBe(false),
    );
    fireEvent.click(saveButton);
    await waitFor(() =>
      expect(saveGlobalDirection).toHaveBeenCalledWith(
        "详细细节：结构、材质、颜色、环境、光线。",
        "glass windshield",
      ),
    );
  });
});
