import unittest as ut
import Screen2DictBot as bt


class MockUser:
    id = 6337812367
    full_name = 'Mock User'


class MockMessage:
    def __init__(self):
        self.user_from = MockUser()


class MockUpdate:
    def __init__(self):
        self.message = MockMessage()


class TestStart(ut.TestCase):
    def test_start(self):
        update = MockUpdate()
        context = bt.CallbackContext()
        bt.start(update, context)
        pass

    pass
