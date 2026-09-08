import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  basePath: "/gizmo",
  devIndicators: false,
  async headers() {
    return [
      {
        source: "/oddity",
        headers: [
          {
            key: "Permissions-Policy",
            value: 'camera=(self "https://gizmo-brain-production.up.railway.app" "http://127.0.0.1:43148"), microphone=(self "https://gizmo-brain-production.up.railway.app" "http://127.0.0.1:43148")',
          },
          { key: "X-Robots-Tag", value: "noindex, nofollow" },
        ],
      },
    ];
  },
  async redirects() {
    return [
      {
        source: "/",
        destination: "/gizmo",
        permanent: false,
        basePath: false,
      },
      {
        source: "/v2",
        destination: "/",
        permanent: false,
      },
      {
        source: "/about",
        destination: "/manifesto",
        permanent: false,
      },
    ];
  },
};

export default nextConfig;
