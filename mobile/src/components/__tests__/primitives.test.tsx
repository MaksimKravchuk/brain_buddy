import { act, fireEvent, render, screen } from "@testing-library/react-native";
import { Pressable, Text } from "react-native";

import { BBText } from "@/components/BBText";
import { EmptyState } from "@/components/EmptyState";
import { Screen } from "@/components/Screen";
import { Sheet } from "@/components/Sheet";
import { ToastHost, useToast } from "@/components/ToastHost";
import { PulsingMic } from "@/components/braindump/PulsingMic";
import { Waveform } from "@/components/braindump/Waveform";
import { StatePicker } from "@/features/tasks/StatePicker";

describe("BBText", () => {
  it.each(["display", "title", "subtitle", "body", "caption", "micro", "label"] as const)(
    "renders the %s variant",
    async (variant) => {
      await render(<BBText variant={variant}>Sample</BBText>);
      expect(screen.getByText("Sample")).toBeOnTheScreen();
    },
  );

  it("applies an explicit weight and colour over the variant defaults", async () => {
    await render(
      <BBText variant="body" weight="bold" color="#123456">
        Sample
      </BBText>,
    );

    expect(screen.getByText("Sample")).toHaveStyle({ color: "#123456" });
  });

  it("passes through the underlying Text props", async () => {
    await render(<BBText numberOfLines={2}>Sample</BBText>);

    expect(screen.getByText("Sample")).toHaveProp("numberOfLines", 2);
  });
});

describe("EmptyState", () => {
  it("shows the headline alone when there is no hint or action", async () => {
    await render(<EmptyState headline="Inbox zero" />);

    expect(screen.getByText("Inbox zero")).toBeOnTheScreen();
  });

  it("shows the hint and a single call to action", async () => {
    await render(
      <EmptyState headline="Inbox zero" hint="Capture anything below.">
        <Text>Add a task</Text>
      </EmptyState>,
    );

    expect(screen.getByText("Capture anything below.")).toBeOnTheScreen();
    expect(screen.getByText("Add a task")).toBeOnTheScreen();
  });
});

describe("Screen", () => {
  it("renders its children", async () => {
    await render(
      <Screen>
        <Text>Body</Text>
      </Screen>,
    );

    expect(screen.getByText("Body")).toBeOnTheScreen();
  });

  it("accepts the safe-area padding flags", async () => {
    const { toJSON } = await render(
      <Screen padTop padBottom style={{ opacity: 0.5 }}>
        <Text>Body</Text>
      </Screen>,
    );

    expect(toJSON()).not.toBeNull();
    expect(screen.getByText("Body")).toBeOnTheScreen();
  });
});

describe("Sheet", () => {
  it("renders its title and body when visible", async () => {
    await render(
      <Sheet visible onClose={jest.fn()} title="Due date">
        <Text>Body</Text>
      </Sheet>,
    );

    expect(screen.getByText("Due date")).toBeOnTheScreen();
    expect(screen.getByText("Body")).toBeOnTheScreen();
  });

  it("omits the title row when there is no title", async () => {
    await render(
      <Sheet visible onClose={jest.fn()}>
        <Text>Body</Text>
      </Sheet>,
    );

    expect(screen.getByText("Body")).toBeOnTheScreen();
  });

  it("closes from the scrim", async () => {
    const onClose = jest.fn();
    await render(
      <Sheet visible onClose={onClose}>
        <Text>Body</Text>
      </Sheet>,
    );

    await fireEvent.press(screen.getByLabelText("Close"));

    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("hides its content when not visible", async () => {
    await render(
      <Sheet visible={false} onClose={jest.fn()} title="Due date">
        <Text>Body</Text>
      </Sheet>,
    );

    expect(screen.queryByText("Body")).toBeNull();
  });
});

describe("StatePicker", () => {
  it("offers all four open lists by default", async () => {
    await render(<StatePicker value={null} onChange={jest.fn()} />);

    for (const label of ["Inbox", "Next", "Waiting", "Someday"]) {
      expect(screen.getByText(label)).toBeOnTheScreen();
    }
  });

  it("offers only the states it was given", async () => {
    await render(<StatePicker value={null} onChange={jest.fn()} options={["next", "waiting"]} />);

    expect(screen.getByText("Next")).toBeOnTheScreen();
    expect(screen.queryByText("Inbox")).toBeNull();
  });

  it("marks the chosen state as selected and reports a new choice", async () => {
    const onChange = jest.fn();
    await render(<StatePicker value="waiting" onChange={onChange} />);

    expect(screen.getByRole("button", { selected: true })).toHaveTextContent("Waiting");

    await fireEvent.press(screen.getByText("Someday"));
    expect(onChange).toHaveBeenCalledWith("someday");
  });
});

describe("ToastHost", () => {
  function Trigger() {
    const toast = useToast();
    return (
      <Pressable accessibilityLabel="notify" onPress={() => toast("Saved 2 to inbox")}>
        <Text>notify</Text>
      </Pressable>
    );
  }

  it("shows a message and clears it after its dwell time", async () => {
    jest.useFakeTimers({ doNotFake: ["nextTick"] });
    try {
      await render(
        <ToastHost>
          <Trigger />
        </ToastHost>,
      );

      await fireEvent.press(screen.getByLabelText("notify"));
      expect(screen.getByText("Saved 2 to inbox")).toBeOnTheScreen();

      await act(async () => {
        await jest.advanceTimersByTimeAsync(2500);
      });
      expect(screen.queryByText("Saved 2 to inbox")).toBeNull();
    } finally {
      jest.useRealTimers();
    }
  });

  it("restarts the dwell time when a second message arrives", async () => {
    jest.useFakeTimers({ doNotFake: ["nextTick"] });
    try {
      await render(
        <ToastHost>
          <Trigger />
        </ToastHost>,
      );

      await fireEvent.press(screen.getByLabelText("notify"));
      await act(async () => {
        await jest.advanceTimersByTimeAsync(2000);
      });
      await fireEvent.press(screen.getByLabelText("notify"));

      await act(async () => {
        await jest.advanceTimersByTimeAsync(1000);
      });
      expect(screen.getByText("Saved 2 to inbox")).toBeOnTheScreen();
    } finally {
      jest.useRealTimers();
    }
  });

  it("renders its children with no toast to begin with", async () => {
    await render(
      <ToastHost>
        <Text>App</Text>
      </ToastHost>,
    );

    expect(screen.getByText("App")).toBeOnTheScreen();
    expect(screen.queryByText("Saved 2 to inbox")).toBeNull();
  });

  it("does nothing when used outside a host, rather than throwing", async () => {
    await render(<Trigger />);

    await expect(fireEvent.press(screen.getByLabelText("notify"))).resolves.toBeUndefined();
  });
});

describe("PulsingMic", () => {
  it("renders the expanding ring only while active", async () => {
    const active = await render(<PulsingMic active />);
    const activeTree = JSON.stringify(active.toJSON());

    const idle = await render(<PulsingMic active={false} />);
    const idleTree = JSON.stringify(idle.toJSON());

    expect(activeTree).not.toBe(idleTree);
  });

  it("accepts an explicit size", async () => {
    const { toJSON } = await render(<PulsingMic active size={64} />);
    expect(toJSON()).not.toBeNull();
  });
});

describe("Waveform", () => {
  it("draws a flat baseline while idle", async () => {
    const { toJSON } = await render(<Waveform active={false} bars={4} />);

    const tree = JSON.stringify(toJSON());
    expect(tree).toContain('"height":8.08');
  });

  it("advances the bars from live metering while recording", async () => {
    jest.useFakeTimers({ doNotFake: ["nextTick"] });
    try {
      const { toJSON } = await render(<Waveform active metering={0} bars={4} />);
      const before = JSON.stringify(toJSON());

      await act(async () => {
        await jest.advanceTimersByTimeAsync(200);
      });

      expect(JSON.stringify(toJSON())).not.toBe(before);
    } finally {
      jest.useRealTimers();
    }
  });

  it("starts a new recording from silence rather than the last one's tail", async () => {
    jest.useFakeTimers({ doNotFake: ["nextTick"] });
    try {
      const { rerender, toJSON } = await render(<Waveform active metering={0} bars={4} />);
      await act(async () => {
        await jest.advanceTimersByTimeAsync(1000);
      });
      const loud = JSON.stringify(toJSON());

      await rerender(<Waveform active={false} metering={0} bars={4} />);
      const idle = JSON.stringify(toJSON());
      await rerender(<Waveform active metering={0} bars={4} />);

      expect(loud).not.toBe(idle);
      expect(JSON.stringify(toJSON())).toBe(idle);
    } finally {
      jest.useRealTimers();
    }
  });
});
