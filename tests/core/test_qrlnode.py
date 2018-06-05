from unittest import TestCase, expectedFailure
from mock import Mock, patch, PropertyMock

from qrl.core import config
from qrl.core.AddressState import AddressState
from qrl.core.Block import Block
from qrl.core.BlockMetadata import BlockMetadata
from qrl.core.ESyncState import ESyncState
from qrl.core.qrlnode import QRLNode
from qrl.core.State import State
from qrl.core.txs.TransferTransaction import TransferTransaction
from qrl.core.txs.TokenTransaction import TokenTransaction
from qrl.core.txs.TransferTokenTransaction import TransferTokenTransaction
from qrl.core.txs.MessageTransaction import MessageTransaction
from qrl.core.txs.SlaveTransaction import SlaveTransaction
from qrl.core.ChainManager import ChainManager
from qrl.core.p2p.p2pprotocol import P2PProtocol
from qrl.core.p2p.p2pPeerManager import P2PPeerManager
from qrl.core.p2p.p2pChainManager import P2PChainManager
from qrl.core.node import POW
from qrl.generated import qrl_pb2
from pyqrllib.pyqrllib import hstr2bin

from tests.core.test_State import gen_blocks
from tests.misc.helper import set_qrl_dir, get_alice_xmss, get_slave_xmss, replacement_getTime

alice = get_alice_xmss()
slave = get_slave_xmss()


@patch('qrl.core.misc.ntp.getTime', new=replacement_getTime)
class TestQRLNodeReal(TestCase):
    @patch('qrl.core.misc.ntp.getTime', new=replacement_getTime)
    def setUp(self):
        # You have to set_qrl_dir to an empty one, otherwise State will have some Transactions from disk
        with set_qrl_dir('no_data'):
            self.db_state = State()
            self.chainmanager = ChainManager(self.db_state)
            self.qrlnode = QRLNode(db_state=self.db_state, mining_address=b'')
            self.qrlnode.set_chain_manager(self.chainmanager)

    @patch('qrl.core.qrlnode.QRLNode.block_height', new_callable=PropertyMock, return_value=19)
    def test_get_latest_blocks(self, m_height):
        # [Block 0, Block 1, Block 2... Block 19]
        blocks = gen_blocks(20, self.db_state, alice.address)

        # get_latest_blocks(offset=0, count=1) from [Block 0.... Block 19] should return [Block 19]
        latest_blocks = self.qrlnode.get_latest_blocks(0, 1)
        self.assertTrue(latest_blocks[0] == blocks[19])  # These are different instances, so cannot use assertEqual

        # get_latest_blocks(offset=0, count=2) from [Block 0.... Block 19] should return [Block 18, Block 19]
        latest_blocks = self.qrlnode.get_latest_blocks(0, 2)
        self.assertTrue(latest_blocks[0] == blocks[18])
        self.assertTrue(latest_blocks[1] == blocks[19])

        # get_latest_blocks(offset=10, count=3) from [Block 0.... Block 19] should return [Block 7 - Block 9]
        latest_blocks = self.qrlnode.get_latest_blocks(10, 3)
        self.assertTrue(latest_blocks[0] == blocks[7])
        self.assertTrue(latest_blocks[1] == blocks[8])
        self.assertTrue(latest_blocks[2] == blocks[9])


@patch('qrl.core.misc.ntp.getTime', new=replacement_getTime)
class TestQRLNode(TestCase):
    @patch('qrl.core.misc.ntp.getTime', new=replacement_getTime)
    def setUp(self):
        self.db_state = Mock(autospec=State, name='mocked State')
        # self.db_state = State()

        self.qrlnode = QRLNode(db_state=self.db_state, mining_address=b'')

        # As the QRLNode is instantiated and torn down for each test, the minuscule or negative diff between present
        # time and start_time can cause problems.
        self.qrlnode.start_time -= 10

        self.qrlnode._pow = Mock(autospec=POW)
        self.qrlnode.peer_manager = Mock(autospec=P2PPeerManager, name='mock P2PPeerManager',
                                         known_peer_addresses=set())
        self.qrlnode.p2pchain_manager = Mock(autospec=P2PChainManager, name='mock P2PChainManager')

        self.chain_manager = Mock(autospec=ChainManager, name='mock ChainManager', height=2)
        mock_last_block = Mock(autospec=Block, name='mock last Block', block_number=2, headerhash=b'deadbeef')
        self.chain_manager.get_last_block.return_value = mock_last_block
        self.qrlnode.set_chain_manager(self.chain_manager)

    def test_monitor_chain_state_no_peer_with_higher_difficulty_found(self):
        """
        QRLNode.monitor_chain_state() basically:
        1. Tells P2PPeerManager to clean the list of channels/P2PProtocols, i.e. remove any we haven't heard
        from for a long time, and make sure our list of channels and the list of their statuses is in sync.
        2. Gets the last block from the State
        3. Broadcasts our State based on the last Block to our peers
        4. Ask P2PPeerManager to return the channel (if any) who has a higher difficulty than our chain.
        If no channel with a higher difficulty is found, nothing else happens.
        """
        m_block = Mock(autospec=Block, name='mock last Block', block_number=2, headerhash=b'deadbeef')
        m_block_metadata = Mock(autospec=BlockMetadata, cumulative_difficulty=hstr2bin('01'))
        self.qrlnode.peer_manager.get_better_difficulty.return_value = None
        self.db_state.get_block_metadata.return_value = m_block_metadata
        self.chain_manager.get_last_block.return_value = m_block

        self.qrlnode.monitor_chain_state()

        self.qrlnode.peer_manager.monitor_chain_state.assert_called_once()
        self.qrlnode.peer_manager.get_better_difficulty.assert_called_once()

    def test_monitor_chain_state_peer_with_higher_difficulty_found(self):
        """
        QRLNode.monitor_chain_state() basically:
        1. Tells P2PPeerManager to clean the list of channels/P2PProtocols, i.e. remove any we haven't heard
        from for a long time, and make sure our list of channels and the list of their statuses is in sync.
        2. Gets the last block from the State
        3. Broadcasts our State based on the last Block to our peers
        4. Ask P2PPeerManager to return the channel (if any) who has a higher difficulty than our chain.
        If a channel with a higher difficulty is found, get its list of headerhashes.
        """
        m_block = Mock(autospec=Block, name='mock last Block', block_number=2, headerhash=b'deadbeef')
        m_block_metadata = Mock(autospec=BlockMetadata, cumulative_difficulty=hstr2bin('01'))
        m_channel = Mock(autospec=P2PProtocol, addr_remote='1.1.1.1')
        self.qrlnode.peer_manager.get_better_difficulty.return_value = m_channel
        self.db_state.get_block_metadata.return_value = m_block_metadata
        self.chain_manager.get_last_block.return_value = m_block

        self.qrlnode.monitor_chain_state()

        self.qrlnode.peer_manager.monitor_chain_state.assert_called_once()
        self.qrlnode.peer_manager.get_better_difficulty.assert_called_once()
        m_channel.send_get_headerhash_list.assert_called_once()

    def test_start_listening(self):
        """
        start_listening() is a convenience function that creates a P2PFactory and connects various components to it
        so that the P2PFactory can function.
        It connects itself, the ChainManager, and the PeerManager to the P2PFactory.
        Then it just tells the P2PFactory to start listening.
        Not much to test here.
        """
        self.assertIsNone(self.qrlnode._p2pfactory)
        self.qrlnode.start_listening()
        self.assertIsNotNone(self.qrlnode._p2pfactory)

    def test_get_address_is_used(self):
        """
        QRLNode.get_address_is_used() asks the DB (State) if a particular address has ever been used.
        It also validates the address before sending it to the State.
        """
        self.db_state.address_used.return_value = True
        result = self.qrlnode.get_address_is_used(alice.address)
        self.assertTrue(result)

        self.db_state.address_used.return_value = False
        result = self.qrlnode.get_address_is_used(alice.address)
        self.assertFalse(result)

        with self.assertRaises(ValueError):
            self.qrlnode.get_address_is_used(b'fdsa')

    def test_get_address_state(self):
        """
        QRLNode.get_address_state() asks the DB (State) for an Address's AddressState, like its nonce, ots index...
        It also validates the address before sending it to the State.
        """
        m_addr_state = Mock(autospec=AddressState)
        self.db_state.get_address_state.return_value = m_addr_state
        result = self.qrlnode.get_address_state(alice.address)
        self.assertEqual(m_addr_state, result)

        with self.assertRaises(ValueError):
            self.qrlnode.get_address_state(b'fdsa')

    def test_get_addr_from(self):
        """
        A master XMSS tree may use a slave XMSS tree to sign for it. If this is the case, we still want to say that the
        TX came from the master XMSS tree, not the slave.
        """
        answer = self.qrlnode.get_addr_from(slave.pk, alice.address)
        self.assertEqual(answer, alice.address)

        answer = self.qrlnode.get_addr_from(slave.pk, None)
        self.assertEqual(answer, slave.address)

    # Just testing that these wrapper functions are doing what they're supposed to do.
    def test_get_transaction(self):
        self.qrlnode.get_transaction(b'a txhash')
        self.chain_manager.get_transaction.assert_called_once_with(b'a txhash')

    def test_get_unconfirmed_transaction(self):
        self.qrlnode.get_unconfirmed_transaction(b'a txhash')
        self.chain_manager.get_unconfirmed_transaction.assert_called_once_with(b'a txhash')

    def test_get_block_last(self):
        self.qrlnode.get_block_last()
        self.chain_manager.get_last_block.assert_called_once()

    def test_get_block_from_hash(self):
        self.qrlnode.get_block_from_hash(b'a blockhash')
        self.db_state.get_block.assert_called_once_with(b'a blockhash')

    def test_get_block_from_index(self):
        self.qrlnode.get_block_from_index(3)
        self.db_state.get_block_by_number.assert_called_once_with(3)

    def test_get_blockidx_from_txhash(self):
        self.db_state.get_tx_metadata.return_value = (Mock(name='Mock TX'), 3)
        result = self.qrlnode.get_blockidx_from_txhash(b'a txhash')
        self.assertEqual(result, 3)

        self.db_state.get_tx_metadata.return_value = None
        result = self.qrlnode.get_blockidx_from_txhash(b'a txhash')
        self.assertIsNone(result)

    def test_get_block_to_mine(self):
        m_block = Mock(autospec=Block, name='mock Block')
        m_block_metadata = Mock(autospec=BlockMetadata, name='mock BlockMetadata', block_difficulty=0)
        self.chain_manager.get_last_block.return_value = m_block
        self.chain_manager.state.get_block_metadata.return_value = m_block_metadata

        self.qrlnode.get_block_to_mine(alice.address)
        self.chain_manager.get_last_block.assert_called_once()
        self.chain_manager.state.get_block_metadata.assert_called_once()
        self.qrlnode._pow.miner.get_block_to_mine.assert_called_once_with(alice.address, self.chain_manager.tx_pool,
                                                                          m_block, 0)

    def test_submit_mined_block(self):
        self.qrlnode.submit_mined_block(b'blob')
        self.qrlnode._pow.miner.submit_mined_block.assert_called_once_with(b'blob')

    def test_get_node_info(self):
        # I guess this test is useful for making sure every part of QRLNode is adequately mocked
        ans = self.qrlnode.get_node_info()
        self.assertIsInstance(ans, qrl_pb2.NodeInfo)

    @expectedFailure
    def test_get_latest_transactions(self):
        """
        This returns the last n txs, just like get_latest_blocks().
        Useful for the Block Explorer, presumably.
        FAIL: this returns the first n transactions.
        """
        self.db_state.get_last_txs.return_value = [Mock(name='mock TX {}'.format(i), i=i) for i in range(0, 20)]

        # Given [0, 1, 2... 19], with offset 0 count 1 should return [19]
        result = self.qrlnode.get_latest_transactions(0, 1)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].i, 19)

        # Given [0, 1, 2... 19], with offset 2 count 3 should return [15, 16, 17]
        result = self.qrlnode.get_latest_transactions(2, 3)
        self.assertEqual(len(result), 3)
        self.assertEqual(result[0].i, 15)
        self.assertEqual(result[1].i, 16)
        self.assertEqual(result[2].i, 17)

    @expectedFailure
    def test_get_latest_transactions_unconfirmed(self):
        """
        This should return the last n unconfirmed txs in the txpool.
        Useful for the Block Explorer, presumably.
        FAIL: this returns the first n unconfirmed transactions.
        """
        self.chain_manager.tx_pool.transactions = [Mock(name='mock TX {}'.format(i), i=i) for i in range(0, 20)]

        # Given [0, 1, 2... 19], with offset 0 count 1 should return [19]
        result = self.qrlnode.get_latest_transactions_unconfirmed(0, 1)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].i, 19)

        # Given [0, 1, 2... 19], with offset 2 count 3 should return [15, 16, 17]
        result = self.qrlnode.get_latest_transactions_unconfirmed(2, 3)
        self.assertEqual(len(result), 3)
        self.assertEqual(result[0].i, 15)
        self.assertEqual(result[1].i, 16)
        self.assertEqual(result[2].i, 17)

    def test_get_block_timeseries(self):
        """
        get_block_timeseries() returns a list of stats for the last n blocks.
        The resultant list is in ascending order of time.
        Useful for the Block Explorer, definitely.
        """
        m_blockdps = {
            b'1': Mock(name='BlockDatapoint 1', header_hash=b'1', header_hash_prev=None),
            b'2': Mock(name='BlockDatapoint 2', header_hash=b'2', header_hash_prev=b'1'),
            b'3': Mock(name='BlockDatapoint 3', header_hash=b'3', header_hash_prev=b'2'),
            b'4': Mock(name='BlockDatapoint 4', header_hash=b'4', header_hash_prev=b'3'),
            b'5': Mock(name='BlockDatapoint 5', header_hash=b'5', header_hash_prev=b'4')
        }
        m_blockdps_as_list = [m_blockdps[key] for key in sorted(m_blockdps.keys())]

        self.chain_manager.get_last_block.return_value = Mock(name='Block 5', headerhash=b'5')

        def replacement_get_block_datapoint(headerhash_current):
            return m_blockdps.get(headerhash_current)

        self.chain_manager.state.get_block_datapoint = replacement_get_block_datapoint

        # Get last 5 blocks should return [BlockDatapoint 1, BlockDatapoint 2... BlockDatapoint 5]
        result = self.qrlnode.get_block_timeseries(5)
        result_converted_from_iterator = [r for r in result]
        self.assertEqual(result_converted_from_iterator, m_blockdps_as_list)

        # Get last 3 blocks should return [BlockDatapoint 3, BlockDatapoint 4... BlockDatapoint 5]
        result = self.qrlnode.get_block_timeseries(3)
        result_converted_from_iterator = [r for r in result]
        self.assertEqual(result_converted_from_iterator, m_blockdps_as_list[2:])

        # If we have a blockheight of 0, return []
        with patch('qrl.core.qrlnode.QRLNode.block_height', new_callable=PropertyMock, return_value=0):
            result = self.qrlnode.get_block_timeseries(3)
            result_converted_from_iterator = [r for r in result]  # []
            self.assertFalse(result_converted_from_iterator)

        # If chain_manager.get_last_block() returns a None, return [] (how is this different from blockheight=0?)
        self.chain_manager.get_last_block.return_value = None
        result = self.qrlnode.get_block_timeseries(5)
        result_converted_from_iterator = [r for r in result]
        self.assertFalse(result_converted_from_iterator)
        self.chain_manager.get_last_block.return_value = Mock(name='Block 5', headerhash=b'5')

        # If we request 6 blocks when we actually have 5, it should still return 5 objects.
        result = self.qrlnode.get_block_timeseries(6)
        result_converted_from_iterator = [r for r in result]
        self.assertEqual(result_converted_from_iterator, m_blockdps_as_list)

    @patch('qrl.core.qrlnode.QRLNode.block_height', new_callable=PropertyMock, return_value=3)
    def test_get_blockheader_and_metadata(self, m_height):
        blocks = []
        for i in range(0, 4):
            m = Mock(name='mock Block {}'.format(i), i=i)
            m.blockheader.headerhash = str(i).encode()
            blocks.append(m)

        block_metadata = {
            b'0': Mock(name='mock BlockMetadata 0', i=0),
            b'1': Mock(name='mock BlockMetadata 1', i=1),
            b'2': Mock(name='mock BlockMetadata 2', i=2),
            b'3': Mock(name='mock BlockMetadata 3', i=3),
        }

        def replacement_get_block_by_number(idx):
            return blocks[idx]

        def replacement_get_block_metadata(headerhash):
            return block_metadata[headerhash]

        self.db_state.get_block_by_number = replacement_get_block_by_number
        self.db_state.get_block_metadata = replacement_get_block_metadata

        # Because we're just using indexes of a list, we can't actually ever return blocks[0]
        # But this shouldn't be a problem because IRL this uses hashes, not indexes.
        # get_blockheader_and_metadata(0) means get the latest block, which is #3
        result_header, result_metadata = self.qrlnode.get_blockheader_and_metadata(0)
        self.assertEqual(result_header, blocks[-1].blockheader)
        self.assertEqual(result_metadata, block_metadata[b'3'])

        # get block 1 returns the second element of blocks[], which happens to be #1
        result_header, result_metadata = self.qrlnode.get_blockheader_and_metadata(1)
        self.assertEqual(result_header, blocks[1].blockheader)
        self.assertEqual(result_metadata, block_metadata[b'1'])

        # get block 3 returns the fourth element of blocks[], which happens to be #3
        result_header, result_metadata = self.qrlnode.get_blockheader_and_metadata(3)  # get block #3
        self.assertEqual(result_header, blocks[3].blockheader)
        self.assertEqual(result_metadata, block_metadata[b'3'])

        # If get_block_by_number() couldn't find the corresponding block, we should get a (None, None)
        self.db_state.get_block_by_number = Mock(return_value=None)
        result_header, result_metadata = self.qrlnode.get_blockheader_and_metadata(2)
        self.assertIsNone(result_header)
        self.assertIsNone(result_metadata)

    def test_submit_send_tx(self):
        # We verify that P2PFactory.add_unprocessed_txn() won't be called when:
        # TX is None OR
        # pending TXPool is full
        with self.assertRaises(ValueError):
            self.qrlnode.submit_send_tx(None)

        self.chain_manager.tx_pool.is_full_pending_transaction_pool.return_value = True
        m_tx = Mock(name='mock Transaction')
        with self.assertRaises(ValueError):
            self.qrlnode.submit_send_tx(m_tx)

        self.chain_manager.tx_pool.is_full_pending_transaction_pool.return_value = False
        self.qrlnode._p2pfactory = Mock(name='mock P2PFactory')
        self.qrlnode.submit_send_tx(m_tx)
        self.qrlnode._p2pfactory.add_unprocessed_txn.assert_called_once()


@patch('qrl.core.misc.ntp.getTime', new=replacement_getTime)
class TestQRLNodeProperties(TestCase):
    @patch('qrl.core.misc.ntp.getTime', new=replacement_getTime)
    def setUp(self):
        self.m_chain_manager = Mock(name='mock ChainManager')
        self.m_chain_manager.get_last_block.return_value = None
        self.m_chain_manager.get_block_by_number.return_value = None
        self.m_peer_manager = Mock(name='mock P2PPeerManager')

        self.qrlnode = QRLNode(db_state=None, mining_address=b'')
        self.qrlnode.set_chain_manager(self.m_chain_manager)
        self.qrlnode.peer_manager = self.m_peer_manager

    def test_state(self):
        # If qrlnode._p2pfactory is None, then this should be this value
        self.assertEqual(self.qrlnode.state, ESyncState.unknown.value)

        # Else, it should be whatever this part of p2pfactory says
        m_p2pfactory = Mock()
        m_p2pfactory.sync_state.state.value = "test"
        self.qrlnode._p2pfactory = m_p2pfactory
        self.assertEqual(self.qrlnode.state, "test")

    def test_num_connections(self):
        # If qrlnode._p2pfactory is None, then this should return 0
        self.assertEqual(self.qrlnode.num_connections, 0)

        # otherwise it should return what p2pfactory's num_connections says
        m_p2pfactory = Mock(num_connections=5)
        self.qrlnode._p2pfactory = m_p2pfactory
        self.assertEqual(self.qrlnode.num_connections, 5)

    def test_epoch(self):
        self.assertEqual(self.qrlnode.epoch, 0)

        self.m_chain_manager.get_last_block.return_value = Mock(block_number=5)
        self.assertEqual(self.qrlnode.epoch, (5 // config.dev.blocks_per_epoch))

        self.m_chain_manager.get_last_block.return_value = Mock(block_number=256)
        self.assertEqual(self.qrlnode.epoch, (256 // config.dev.blocks_per_epoch))

    def test_uptime_network(self):
        # If there is no block after the genesis block, this property should return 0
        self.assertEqual(self.qrlnode.uptime_network, 0)

        # However, if there is a block after the genesis block, use its timestamp to calculate our uptime.
        with patch('qrl.core.misc.ntp.getTime') as m_getTime:
            self.m_chain_manager.get_block_by_number.return_value = Mock(timestamp=1000000)
            m_getTime.return_value = 1500000
            self.assertEqual(self.qrlnode.uptime_network, 500000)

    def test_block_last_reward(self):
        # If get_last_block() returned None, of course the last reward was 0.
        self.assertEqual(self.qrlnode.block_last_reward, 0)

        # Else it is what the block_reward says it is.
        self.m_chain_manager.get_last_block.return_value = Mock(block_reward=53)
        self.assertEqual(self.qrlnode.block_last_reward, 53)

    def test_block_time_mean(self):
        # FIXME
        # For this function to work, get_last_block() must not return a None. If it does, bad things will happen.
        self.m_chain_manager.get_last_block.return_value = Mock(name='mock Block')

        # If this particular function returns None, this property should just return the config value
        self.m_chain_manager.state.get_block_metadata.return_value = None
        self.assertEqual(self.qrlnode.block_time_mean, config.dev.mining_setpoint_blocktime)

        # Else, it should consult state.get_measurement()
        self.m_chain_manager.state.get_block_metadata.return_value = Mock(name='mock BlockMetadata')
        self.qrlnode.block_time_mean()
        self.m_chain_manager.state.get_measurement.assert_called_once()

    def test_coin_supply(self):
        m_state = Mock(name='mock State')
        self.qrlnode.db_state = m_state
        self.qrlnode.coin_supply()
        m_state.total_coin_supply.assert_called_once()

    def test_coin_supply_max(self):
        # This property should be whatever config says it is.
        self.assertEqual(self.qrlnode.coin_supply_max, config.dev.max_coin_supply)

    def test_get_peers_stat(self):
        self.qrlnode.get_peers_stat()
        self.m_peer_manager.get_peers_stat.assert_called_once()

    def test_connect_peers(self):
        self.qrlnode.connect_peers()
        self.m_peer_manager.connect_peers.assert_called_once()


@patch('qrl.core.misc.ntp.getTime', new=replacement_getTime)
class TestQRLNodeCreateTX(TestCase):
    @patch('qrl.core.misc.ntp.getTime', new=replacement_getTime)
    def setUp(self):
        self.db_state = Mock(autospec=State, name='mocked State')

        self.qrlnode = QRLNode(db_state=self.db_state, mining_address=b'')

    def test_create_message_txn(self):
        params = {
            'message_hash': b'deadbeef',
            'fee': 1,
            'xmss_pk': alice.pk,
            'master_addr': None
        }
        tx = QRLNode.create_message_txn(**params)
        self.assertIsInstance(tx, MessageTransaction)

    def test_create_token_txn(self):
        params = {
            "symbol": b'QRL',
            "name": b'Quantum Resistant Ledger',
            "owner": alice.address,
            "decimals": 15,
            "initial_balances": [qrl_pb2.AddressAmount(address=alice.address, amount=1000)],
            "fee": 1,
            "xmss_pk": alice.pk,
            "master_addr": None
        }
        tx = QRLNode.create_token_txn(**params)
        self.assertIsInstance(tx, TokenTransaction)

    def test_create_transfer_token_txn(self):
        params = {
            "token_txhash": b'',
            "addrs_to": [slave.address],
            "amounts": [100],
            "fee": 1,
            "xmss_pk": alice.pk,
            "master_addr": None
        }
        tx = QRLNode.create_transfer_token_txn(**params)
        self.assertIsInstance(tx, TransferTokenTransaction)

    def test_create_send_tx(self):
        """
        This wrapper function also checks the addr_from's balance, even though it is also checked elsewhere.
        """
        self.db_state.balance.return_value = 10

        params = {
            "addrs_to": [slave.address],
            "amounts": [100],
            "fee": 1,
            "xmss_pk": alice.pk,
            "master_addr": None,
        }
        with self.assertRaises(ValueError):
            self.qrlnode.create_send_tx(**params)

        self.db_state.balance.return_value = 1000
        tx = self.qrlnode.create_send_tx(**params)
        self.assertIsInstance(tx, TransferTransaction)

    def test_create_slave_tx(self):
        params = {
            "slave_pks": [slave.pk],
            "access_types": [0],
            "fee": 1,
            "xmss_pk": alice.pk,
            "master_addr": None
        }
        tx = self.qrlnode.create_slave_tx(**params)
        self.assertIsInstance(tx, SlaveTransaction)
