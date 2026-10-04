# Side imports
import uvicorn

# Project imports
from walletscanner import create_app


app = create_app()


# For local launch
if __name__ == "__main__":
    uvicorn.run("walletscanner.main:app", host="0.0.0.0", port=8888, reload=True)