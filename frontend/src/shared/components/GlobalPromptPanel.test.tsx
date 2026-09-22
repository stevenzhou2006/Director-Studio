// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const expandProjectDirection = vi.hoisted(() => vi.fn());
const getProjectDirection = vi.hoisted(() => vi.fn());
const saveProjectDirection = vi.hoisted(() => vi.fn());

vi.mock("../../features/director/api", () => ({
  expandProjectDirection,
  getProjectDirection,
  saveProjectDirection,
}));

import { GlobalPromptPanel } from "./GlobalPromptPanel";

describe("GlobalPromptPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getProjectDirection.mockResolvedValue({ detail: "", negative: "" });
    expandProjectDirection.mockResolvedValue(
      "详细细节：结构、材质、颜色、环境、光线。",
    );
    saveProjectDirection.mockResolvedValue({
      detail: "详细细节：结构、材质、颜色、环境、光线。",
      negative: "glass windshield",
    });
  });

  afterEach(() => {
    cleanup();
  });

  it("loads, expands with 生成细节, then saves with 保存项目细节", async () => {
    render(<GlobalPromptPanel projectId="prj_test" />);

    await waitFor(() =>
      expect(getProjectDirection).toHaveBeenCalledWith("prj_test"),
    );

    const saveButton = screen.getByRole("button", { name: "保存项目细节" });
    expect((saveButton as HTMLButtonElement).disabled).toBe(true);

    fireEvent.change(screen.getByPlaceholderText(/整体画面/), {
      target: { value: "雨夜老街的电影感画面" },
    });
    fireEvent.click(screen.getByRole("button", { name: "生成细节" }));

    await waitFor(() =>
      expect(screen.getByDisplayValue(/详细细节/)).toBeTruthy(),
    );
    expect(expandProjectDirection).toHaveBeenCalledWith(
      "prj_test",
      "雨夜老街的电影感画面",
      "",
    );

    fireEvent.change(screen.getByPlaceholderText(/glass windshield/), {
      target: { value: "glass windshield" },
    });

    await waitFor(() =>
      expect((saveButton as HTMLButtonElement).disabled).toBe(false),
    );
    fireEvent.click(saveButton);
    await waitFor(() =>
      expect(saveProjectDirection).toHaveBeenCalledWith(
        "prj_test",
        "详细细节：结构、材质、颜色、环境、光线。",
        "glass windshield",
      ),
    );
  });

  it("prompts for a project when none is selected", () => {
    render(<GlobalPromptPanel />);
    expect(screen.getByText("请先选择一个项目。")).toBeTruthy();
    expect(getProjectDirection).not.toHaveBeenCalled();
  });
});
