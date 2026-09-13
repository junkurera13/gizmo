import unittest

from aioice.ice import TransportPolicy
from aiortc import RTCConfiguration, RTCIceServer, RTCPeerConnection

from gizmo_friend.cinema.stream import (
    force_relay_only,
    reliable_upstream_ice_servers,
)


class DirectorIceTests(unittest.IsolatedAsyncioTestCase):
    def test_upstream_selects_fals_explicit_tcp_turn_relay(self):
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
            RTCIceServer(
                "turns:relay.example:443?transport=tcp",
                username="device",
                credential="secret",
            ),
        ]

        selected = reliable_upstream_ice_servers(servers)

        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0].urls, "turn:relay.example:80?transport=tcp")
        self.assertEqual(selected[0].username, "device")
        self.assertEqual(selected[0].credential, "secret")

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
