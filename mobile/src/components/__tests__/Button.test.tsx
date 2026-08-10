import { fireEvent, render, screen } from "@testing-library/react-native";
import { Text } from "react-native";

import { Button } from "../Button";

describe("Button", () => {
  it("renders a string child as text and calls onPress", async () => {
    const onPress = jest.fn();
    await render(<Button onPress={onPress}>Reopen</Button>);

    await fireEvent.press(screen.getByRole("button"));

    expect(screen.getByText("Reopen")).toBeOnTheScreen();
    expect(onPress).toHaveBeenCalledTimes(1);
  });

  it("renders non-string children as-is", async () => {
    await render(
      <Button>
        <Text>Custom child</Text>
      </Button>,
    );

    expect(screen.getByText("Custom child")).toBeOnTheScreen();
  });

  it("does not fire onPress while disabled", async () => {
    const onPress = jest.fn();
    await render(
      <Button onPress={onPress} disabled>
        Save
      </Button>,
    );

    await fireEvent.press(screen.getByRole("button"));

    expect(onPress).not.toHaveBeenCalled();
  });

  it("swaps the label for a spinner while loading, and stays unpressable", async () => {
    const onPress = jest.fn();
    await render(
      <Button onPress={onPress} loading>
        Save
      </Button>,
    );

    await fireEvent.press(screen.getByRole("button"));

    expect(screen.queryByText("Save")).toBeNull();
    expect(onPress).not.toHaveBeenCalled();
  });

  it("exposes an explicit accessibility label when the child is not text", async () => {
    await render(
      <Button accessibilityLabel="Close menu">
        <Text>×</Text>
      </Button>,
    );

    expect(screen.getByLabelText("Close menu")).toBeOnTheScreen();
  });

  it.each(["primary", "secondary", "ghost", "destructive"] as const)(
    "renders the %s variant",
    async (variant) => {
      await render(
        <Button variant={variant} onPress={jest.fn()}>
          Go
        </Button>,
      );

      expect(screen.getByRole("button")).toBeOnTheScreen();
      expect(screen.getByText("Go")).toBeOnTheScreen();
    },
  );
});
