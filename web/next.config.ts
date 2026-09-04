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
    ];
  },
};

export default nextConfig;
