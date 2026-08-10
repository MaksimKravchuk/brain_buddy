import { fireEvent, render, screen } from "@testing-library/react-native";

import { ApiError } from "@/api/client";

import { ErrorBanner } from "../ErrorBanner";

describe("ErrorBanner", () => {
  it("shows the server message and the correlation reference for an ApiError", async () => {
    const error = new ApiError("Request failed", 409, {
      message: "That task changed while you were editing it.",
      reference_id: "corr-42",
    });

    await render(<ErrorBanner error={error} />);

    expect(screen.getByText("That task changed while you were editing it.")).toBeOnTheScreen();
    expect(screen.getByText("ref: corr-42")).toBeOnTheScreen();
  });

  it("falls back to the correlation id when the payload carries no reference", async () => {
    const error = new ApiError("Boom", 500, null, "corr-from-header");

    await render(<ErrorBanner error={error} />);

    expect(screen.getByText("ref: corr-from-header")).toBeOnTheScreen();
  });

  it("shows a plain Error's message without a reference line", async () => {
    await render(<ErrorBanner error={new Error("Network request failed")} />);

    expect(screen.getByText("Network request failed")).toBeOnTheScreen();
    expect(screen.queryByText(/^ref: /)).toBeNull();
  });

  it("falls back to a generic message for a thrown non-Error", async () => {
    await render(<ErrorBanner error={"just a string"} />);

    expect(screen.getByText("Something went wrong.")).toBeOnTheScreen();
  });

  it("falls back to a generic message for an Error with an empty message", async () => {
    await render(<ErrorBanner error={new Error("")} />);

    expect(screen.getByText("Something went wrong.")).toBeOnTheScreen();
  });

  it("offers Retry only when a retry handler is given", async () => {
    await render(<ErrorBanner error={new Error("Nope")} />);
    expect(screen.queryByText("Retry")).toBeNull();

    const onRetry = jest.fn();
    await render(<ErrorBanner error={new Error("Nope")} onRetry={onRetry} />);
    await fireEvent.press(screen.getByText("Retry"));

    expect(onRetry).toHaveBeenCalledTimes(1);
  });
});
