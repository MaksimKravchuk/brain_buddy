import { fireEvent, render, waitFor } from "@testing-library/react-native";

import { mobileAllure, withAllure } from "@/test/allureTaxonomy";
import { SignInScreen } from "../SignInScreen";

const mockUseAuth = jest.fn();

jest.mock("@/auth/AuthProvider", () => ({
  useAuth: () => mockUseAuth(),
}));

describe("SignInScreen remote logout recovery", () => {
  it(
    mobileAllure.auth("shows unresolved remote revocation and offers a credential-free retry").title,
    async () => {
      await withAllure(
        mobileAllure.auth("shows unresolved remote revocation and offers a credential-free retry"),
        async () => {
          const retryLogout = jest.fn().mockResolvedValue(undefined);
          mockUseAuth.mockReturnValue({
            signIn: jest.fn(),
            logoutRevocationUnresolved: true,
            retryLogout,
          });

          const screen = await render(<SignInScreen />);

          expect(
            screen.getByText(/could not confirm your last sign-out with the server/i),
          ).toBeTruthy();
          await fireEvent.press(screen.getByLabelText("Retry sign-out"));
          await waitFor(() => expect(retryLogout).toHaveBeenCalledTimes(1));
        },
      );
    },
  );
});
