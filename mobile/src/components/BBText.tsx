import { Text, type TextProps, type TextStyle } from "react-native";

import { colors, fonts, tracking, type as typeScale } from "@/theme/tokens";

type Variant = "display" | "title" | "subtitle" | "body" | "caption" | "micro" | "label";
type Weight = "regular" | "medium" | "semibold" | "bold";

const variantStyles: Record<Variant, TextStyle> = {
  display: {
    fontSize: typeScale.display,
    lineHeight: Math.round(typeScale.display * 1.15),
    letterSpacing: tracking.display,
    fontFamily: fonts.semibold,
    color: colors.fg1,
  },
  title: {
    fontSize: typeScale.title,
    lineHeight: Math.round(typeScale.title * 1.3),
    letterSpacing: tracking.title,
    fontFamily: fonts.semibold,
    color: colors.fg1,
  },
  subtitle: {
    fontSize: typeScale.subtitle,
    lineHeight: Math.round(typeScale.subtitle * 1.4),
    letterSpacing: tracking.subtitle,
    fontFamily: fonts.medium,
    color: colors.fg2,
  },
  body: {
    fontSize: typeScale.body,
    lineHeight: Math.round(typeScale.body * 1.5),
    fontFamily: fonts.regular,
    color: colors.fg2,
  },
  caption: {
    fontSize: typeScale.caption,
    lineHeight: Math.round(typeScale.caption * 1.4),
    fontFamily: fonts.regular,
    color: colors.fg5,
  },
  micro: {
    fontSize: typeScale.micro,
    lineHeight: Math.round(typeScale.micro * 1.35),
    fontFamily: fonts.regular,
    color: colors.fg5,
  },
  // The only uppercase in the product: 10px tracked section labels.
  label: {
    fontSize: typeScale.label,
    lineHeight: Math.round(typeScale.label * 1.4),
    letterSpacing: tracking.label,
    textTransform: "uppercase",
    fontFamily: fonts.semibold,
    color: colors.fg5,
  },
};

const weightToFamily: Record<Weight, string> = {
  regular: fonts.regular,
  medium: fonts.medium,
  semibold: fonts.semibold,
  bold: fonts.bold,
};

export interface BBTextProps extends TextProps {
  variant?: Variant;
  weight?: Weight;
  color?: string;
}

export function BBText({ variant = "body", weight, color, style, ...rest }: BBTextProps) {
  return (
    <Text
      {...rest}
      style={[
        variantStyles[variant],
        weight ? { fontFamily: weightToFamily[weight] } : null,
        color ? { color } : null,
        style,
      ]}
    />
  );
}
