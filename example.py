if __name__ == "__main__":
    import nadtcp
    import logging
    import asyncio

    logging.basicConfig(level=logging.DEBUG)

    _LOGGER = logging.getLogger(__name__)

    loop = asyncio.get_event_loop()


    def state_changed(state):
        pass


    client = nadtcp.NADReceiverTCPC338('192.168.1.121', loop, state_changed_cb=state_changed)


    async def test():
        await client.connect()


    loop.run_until_complete(test())

    loop.run_forever()
