if __name__ == "__main__":
    import nadtcp
    import logging
    import asyncio

    logging.basicConfig(level=logging.DEBUG)

    _LOGGER = logging.getLogger(__name__)

    if __name__ == "__main__":
        loop = asyncio.get_event_loop()

        nad_client = nadtcp.NADC338Protocol.create_nad_connection(loop=loop, target_ip='192.168.1.121')

        loop.run_until_complete(nad_client)

        loop.run_forever()
