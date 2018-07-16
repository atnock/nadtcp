if __name__ == "__main__":
    import nadtcp
    import logging
    import asyncio

    logging.basicConfig(level=logging.DEBUG)

    _LOGGER = logging.getLogger(__name__)

    loop = asyncio.get_event_loop()


    async def connect():
        _, nad_client = await nadtcp.NADC338Protocol.create_nad_connection(loop=loop, target_ip='192.168.1.121')

        state = await nad_client.state(force_refresh=True)

        _LOGGER.info("Connected %s" % state)


    loop.run_until_complete(connect())

    loop.run_forever()
