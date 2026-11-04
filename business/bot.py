"""Public entry point for Pakostnik Telegram Business, compatible with the phone launcher."""
from __future__ import annotations
import logging
import signal
from .core import Config, Store, Telegram, OpenAI, APIError, NOTICE, SYSTEM, RISK, DEFAULT_STYLE, MAX_EXAMPLES, EXAMPLE_LIMIT, ALLOWED_UPDATES
from .controller import BusinessBot


def main(values: dict[str,str] | None = None):
    logging.basicConfig(level=logging.INFO,format='%(levelname)s %(message)s')
    instance=None
    try:
        config=Config.env(values)
        instance=BusinessBot(config)
        signal.signal(signal.SIGTERM,lambda *_:instance.request_stop())
        signal.signal(signal.SIGINT,lambda *_:instance.request_stop())
        instance.run()
    except (ValueError,RuntimeError,APIError) as error:
        logging.getLogger('pakostnik.business').error('%s',error)
        raise SystemExit(1) from None
    except OSError:
        logging.getLogger('pakostnik.business').error('Unable to open local state or network resources')
        raise SystemExit(1) from None
    finally:
        if instance:instance.close()


if __name__=='__main__':
    main()
