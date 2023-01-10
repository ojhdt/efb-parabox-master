# coding=utf-8

import itertools
import json
import logging
import time
from json import JSONDecodeError
from typing import TYPE_CHECKING
import threading

from ehforwarderbot import Status
from ehforwarderbot.status import ChatUpdates, MemberUpdates, MessageRemoval, MessageReactionsUpdate

import asyncio
from asyncio.exceptions import TimeoutError
import websockets

# import nest_asyncio
#
# nest_asyncio.apply()

if TYPE_CHECKING:
    from . import ParaboxChannel
    from .db import DatabaseManager


class ServerManager:
    def __init__(self, channel: 'ParaboxChannel'):
        self.logger: logging.Logger = logging.getLogger(__name__)
        self.channel: 'ParaboxChannel' = channel
        self.db: 'DatabaseManager' = channel.db

        self.host = channel.config.get("host")
        self.port = channel.config.get("port")
        self.sending_interval = channel.config.get("sending_interval")

        self.websocket_users = set()
        self.loop = asyncio.new_event_loop()

        threading.Thread(target=self.run_main).start()

    def run_main(self):
        self.loop.run_until_complete(self.server_main())
        self.loop.run_forever()

    async def server_main(self):
        self.logger.info("Websocket listening at %s : %s", self.host, self.port)
        async with websockets.serve(self.handler, self.host, self.port, max_size=1_000_000_000):
            await asyncio.Future()

    async def handler(self, websocket, path):
        if len(self.websocket_users) == 0:
            try:
                await self.check_user_permit(websocket)
                await self.recv_user_msg(websocket)
            except websockets.ConnectionClosed:
                self.logger.info("ConnectionClosed... %s", path)
                self.websocket_users.remove(websocket)
                self.logger.info("Websocket_users: %s", len(self.websocket_users))
            except websockets.InvalidState:
                self.logger.info("InvalidState...")
                self.logger.info("Websocket_users: %s", len(self.websocket_users))
            except Exception as e:
                self.logger.info("Exception Name: %s: %s", type(e).__name__, e)
                self.websocket_users.remove(websocket)
                self.logger.info("Websocket_users: %s", len(self.websocket_users))
        else:
            self.logger.info("Already has a user, reject new user")

    async def check_user_permit(self, websocket):
        token = self.channel.config.get("token")
        while True:
            timeout = 10
            try:
                recv_str = await asyncio.wait_for(websocket.recv(), timeout)
                if recv_str == token:
                    self.logger.info("WebSocket client connected: %s", websocket)
                    self.websocket_users.add(websocket)
                    self.logger.debug("Websocket_users: %s", len(self.websocket_users))
                    await websocket.send(
                        json.dumps({
                            "type": "code",
                            "data": {
                                "code": 4000,
                                "msg": "success"
                            }
                        })
                    )
                    return True
                else:
                    self.logger.info("WebSocket client token incorrect: %s", websocket)
                    await websocket.send(
                        json.dumps({
                            "type": "code",
                            "data": {
                                "code": 1000,
                                "msg": "token incorrect"
                            }
                        })
                    )
                    return False
            except TimeoutError as e:
                self.logger.info("WebSocket client token timeout: %s", websocket)
                await websocket.send(
                    json.dumps({
                        "type": "code",
                        "data": {
                            "code": 1001,
                            "msg": "timeout"
                        }
                    })
                )
                return False

    async def recv_user_msg(self, websocket):
        self.logger.info("recv user msg...")
        while True:
            recv_text = await websocket.recv()
            json_obj = json.loads(recv_text)
            self.channel.master_messages.process_parabox_message(json_obj)
            await asyncio.sleep(1)

    def pulling(self):
        pass

    def graceful_stop(self):
        self.logger.debug("Websocket server stopped")
        self.loop.stop()

    def send_message(self, json_str):
        self.loop.create_task(self.async_send_message(json_str))

    async def async_send_message(self, json_str):
        for websocket in self.websocket_users:
            self.logger.debug("sending ws to: %s", websocket)
            await websocket.send(
                json.dumps({
                    "type": "message",
                    "data": json_str
                })
            )
            await asyncio.sleep(self.sending_interval)

    def send_status(self, status: 'Status'):
        if isinstance(status, ChatUpdates):
            self.logger.debug("Received chat updates from channel %s", status.channel)
            pass
        elif isinstance(status, MemberUpdates):
            self.logger.debug("Received member updates from channel %s about group %s",
                              status.channel, status.chat_id)
            pass
        elif isinstance(status, MessageRemoval):
            self.logger.debug("Received message removal request from channel %s on message %s",
                              status.source_channel, status.message)
            pass
        elif isinstance(status, MessageReactionsUpdate):

            pass
        else:
            self.logger.debug('Received an unsupported type of status: %s', status)
