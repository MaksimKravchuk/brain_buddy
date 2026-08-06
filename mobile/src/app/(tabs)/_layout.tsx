import { Tabs } from "expo-router";
import { Archive, ArrowRight, Clock, Inbox, Layers } from "lucide-react-native";

import { useTaskCounts } from "@/features/tasks/useTaskCounts";
import { colors, fonts } from "@/theme/tokens";

export default function TabsLayout() {
  const counts = useTaskCounts();

  return (
    <Tabs
      screenOptions={{
        headerShown: false,
        tabBarActiveTintColor: colors.brandPrimary,
        tabBarInactiveTintColor: colors.fg5,
        tabBarStyle: {
          backgroundColor: colors.surfaceRaised,
          borderTopColor: colors.border,
        },
        tabBarLabelStyle: {
          fontFamily: fonts.medium,
          fontSize: 10,
        },
        // Inbox count is the only badge — a sky pill, per the design.
        tabBarBadgeStyle: {
          backgroundColor: colors.brandPrimary,
          color: "#FFFFFF",
          fontFamily: fonts.semibold,
          fontSize: 10,
        },
      }}
    >
      <Tabs.Screen
        name="index"
        options={{
          title: "Inbox",
          tabBarIcon: ({ color, size }) => <Inbox color={color} size={size} strokeWidth={1.75} />,
          tabBarBadge: counts && counts.inbox > 0 ? counts.inbox : undefined,
        }}
      />
      <Tabs.Screen
        name="next"
        options={{
          title: "Next",
          tabBarIcon: ({ color, size }) => <ArrowRight color={color} size={size} strokeWidth={1.75} />,
        }}
      />
      <Tabs.Screen
        name="waiting"
        options={{
          title: "Waiting",
          tabBarIcon: ({ color, size }) => <Clock color={color} size={size} strokeWidth={1.75} />,
        }}
      />
      <Tabs.Screen
        name="someday"
        options={{
          title: "Someday",
          tabBarIcon: ({ color, size }) => <Archive color={color} size={size} strokeWidth={1.75} />,
        }}
      />
      <Tabs.Screen
        name="browse"
        options={{
          title: "Browse",
          tabBarIcon: ({ color, size }) => <Layers color={color} size={size} strokeWidth={1.75} />,
        }}
      />
    </Tabs>
  );
}
