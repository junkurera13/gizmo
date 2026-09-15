import unittest

from aioice.ice import TransportPolicy
from aiortc import RTCConfiguration, RTCIceServer, RTCPeerConnection

from gizmo_friend.cinema.stream import (
    force_relay_only,
    ice_servers_payload,
    reliable_upstream_ice_servers,
    turn_url_priority,
    viewer_ice_servers,
)


def fal_ice_servers():
    return [
        RTCIceServer("stun:stun.relay.example:80"),
        RTCIceServer(
            "turn:relay.example:80",
            username="device",
            credential="secret",
        ),
        RTCIceServer(
            "turn:relay.example:80?transport=tcp",
            username="device",
            credential="secret",
        ),
        RTCIceServer(
            "turns:relay.example:443?transport=tcp",
            username="device",
            credential="secret",
        ),
    ]


class DirectorIceTests(unittest.IsolatedAsyncioTestCase):
    def test_turns_is_not_confused_with_turn_prefix(self):
        self.assertEqual(turn_url_priority("turns:relay.example:443?transport=tcp"), 0)
        self.assertEqual(turn_url_priority("turn:relay.example:80?transport=tcp"), 2)
        self.assertIsNone(turn_url_priority("turn:relay.example:80"))
        self.assertIsNone(turn_url_priority("stun:stun.relay.example:80"))

    def test_upstream_prefers_tls_turn_over_port_80_tcp(self):
        selected = reliable_upstream_ice_servers(fal_ice_servers())

        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0].urls, "turns:relay.example:443?transport=tcp")
        self.assertEqual(selected[0].username, "device")
        self.assertEqual(selected[0].credential, "secret")

    def test_upstream_falls_back_to_explicit_tcp_when_tls_is_missing(self):
        servers = [
            RTCIceServer("stun:stun.relay.example:80"),
            RTCIceServer(
                "turn:relay.example:80",
                username="device",
                credential="secret",
            ),
            RTCIceServer(
                "turn:relay.example:80?transport=tcp",
                username="device",
                credential="secret",
            ),
        ]

        selected = reliable_upstream_ice_servers(servers)

        self.assertEqual(selected[0].urls, "turn:relay.example:80?transport=tcp")

    def test_viewer_hop_lists_tls_then_tcp_and_drops_udp(self):
        selected = viewer_ice_servers(fal_ice_servers())
        payload = ice_servers_payload(selected)
        urls = [row["urls"] for row in payload]

        self.assertEqual(urls[0], "stun:stun.relay.example:80")
        self.assertEqual(urls[1], "turns:relay.example:443?transport=tcp")
        self.assertEqual(urls[2], "turn:relay.example:80?transport=tcp")
        self.assertEqual(payload[1]["username"], "device")
        self.assertEqual(payload[1]["credential"], "secret")
        self.assertNotIn("turn:relay.example:80", urls)

    async def test_upstream_gatherers_are_relay_only(self):
        pc = RTCPeerConnection(
            RTCConfiguration(
                iceServers=[
                    RTCIceServer(
                        "turn:relay.example:80?transport=tcp",
                        username="device",
                        credential="secret",
                    )
                ]
            )
        )
        self.addAsyncCleanup(pc.close)
        pc.addTransceiver("video", direction="recvonly")
        pc.addTransceiver("audio", direction="recvonly")
        pc.createDataChannel("control")

        force_relay_only(pc)

        gatherers = [
            transceiver.sender.transport.transport.iceGatherer
            for transceiver in pc.getTransceivers()
        ]
        gatherers.append(pc.sctp.transport.transport.iceGatherer)
        self.assertTrue(gatherers)
        self.assertTrue(
            all(
                gatherer._connection._transport_policy == TransportPolicy.RELAY
                for gatherer in gatherers
            )
        )


if __name__ == "__main__":
    unittest.main()
