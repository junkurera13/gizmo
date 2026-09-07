import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  basePath: "/gizmo",
  devIndicators: false,
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
    ];
  },
};

export default nextConfig;
