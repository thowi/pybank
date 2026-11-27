import "@fontsource-variable/plus-jakarta-sans";
import "@mantine/core/styles.css";
import "@mantine/notifications/styles.css";
import "@mantine/spotlight/styles.css";
import { createTheme, MantineProvider } from "@mantine/core";
import { Notifications } from "@mantine/notifications";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";

// The brand ramp and type of the other local apps, so they look alike.
const BRAND = [
  "#edf8f4", "#d3eee5", "#ade1d0", "#7dd4b8", "#49caa1",
  "#26ab81", "#15795a", "#11694d", "#0d5941", "#0a4834",
] as const;
const FONT = '"Plus Jakarta Sans Variable", system-ui, sans-serif';

const theme = createTheme({
  colors: { brand: [...BRAND] },
  defaultRadius: "md",
  fontFamily: FONT,
  headings: { fontFamily: FONT, fontWeight: "700" },
  primaryColor: "brand",
  primaryShade: { dark: 5, light: 6 },
});

// The review is a snapshot. A refetch would put answered cards back.
const queryClient = new QueryClient({
  defaultOptions: { queries: { refetchOnWindowFocus: false, staleTime: Infinity } },
});

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <MantineProvider theme={theme} defaultColorScheme="auto">
      <Notifications position="bottom-right" />
      <QueryClientProvider client={queryClient}>
        <App />
      </QueryClientProvider>
    </MantineProvider>
  </React.StrictMode>,
);
