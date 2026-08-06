import { Redirect } from "expo-router";

/** Next actions is the signed-in landing list, matching the product. */
export default function Index() {
  return <Redirect href="/list/next" />;
}
