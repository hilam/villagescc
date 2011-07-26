"Network flow computations."

import networkx as nx
from decimal import Decimal as D

from django.conf import settings

from cc.account.models import CreditLine, AmountField


class PaymentError(Exception):
    "Base class for all payment exceptions."
    pass

class NoRoutesError(PaymentError):
    "No possible routes between payer and recipient."
    pass

class InsufficientCreditError(PaymentError):
    "Not enough max flow between payer and recipient to make payment."
    def __init__(self, amount_found):
        self.amount_found = amount_found

        
class FlowLinkSet(object):
    "A set of paths found for performing a payment."
    def __init__(self, payment):
        self.payment = payment
        self._compute()

    def _compute(self):
        """
        Compute min cost flow between payer and recipient.
        
        Raises NoRoutesError if there is no route from payer to recipient.
        """
        self.src_creditlines = self.payment.payer.out_creditlines()
        graph = self._flow_graph()
        self._set_endpoint_demand(graph)
        if graph.degree(self.payment.recipient_id) == 0:
            raise NoRoutesError()
        #import pdb; pdb.set_trace()
        try:
            cost, self.flow_dict = nx.network_simplex(graph)
        except nx.NetworkXUnfeasible:
            available = nx.max_flow(
                graph, self.payment.payer_id, self.payment.recipient_id)
            raise InsufficientCreditError(amount_found=available)
        self.graph = graph
            
    def _flow_graph(self):
        """
        Get flow graph for performing payment computations for this payment.
        
        A flow graph is a connected directed networkx DiGraph where the edges
        represent account-halves and exchanges between them performed by various
        users.  Payment always flows from credit line owner to the other
        partner.

        A flow graph contains all credit lines that could possibly be used to
        transfer value from payer to recipient.  It may also contain other
        account-halves so it can be cached and used for other payments.  For
        example, the flow graph might contain the set of all nodes that could
        pay or be paid by the payer.

        The flow graph assigns costs to each credit line edge in order prioritize
        settling balances.

        To use this graph in the min cost demand flow algorithm, assign the payer
        a supply (negative demand) and the recipient a demand equal to the payment
        amount.
        """
        # TODO: Generate complete connected flow graph such that for every
        # vertex in graph, it includes every possible incoming and outgoing
        # edge.  Assign each such flow graph an ID, and store the ID of
        # the unique flow graph it belongs to at each CreditLine so the flow
        # graph can be quickly generated by loading the account halves in one
        # go.  Then cache each complete flow graph for re-use in other payments.

        graph = nx.DiGraph()
        visited_creditline_ids = {}  # Indexed by user profile id.
        pending_creditlines = list(self.src_creditlines)
        while pending_creditlines:
            curr_creditline = pending_creditlines.pop(0)

            # Add creditline edge(s) to graph.
            self._add_creditline_to_graph(graph, curr_creditline)
            visited_creditline_ids.setdefault(
                curr_creditline.node_id, set()).add(curr_creditline.id)
            
            # Add partner's unvisited outgoing credit lines to pending
            # list for eventual visitation.
            partner = curr_creditline.partner
            next_creditlines = partner.out_creditlines().exclude(
                pk__in=visited_creditline_ids.get(partner.id, []))
            pending_creditlines += list(next_creditlines)
        return graph

    def _add_creditline_to_graph(self, graph, creditline):
        src = creditline.node_id
        dest = creditline.partner.id
        chunks = creditline.payment_cost()
        # Add first edge normally.
        capacity, weight = chunks[0]
        graph.add_edge(src, dest, weight=weight, capacity=capacity,
                       creditline=creditline)
        for i, chunk in enumerate(chunks[1:]):
            # For multiple edges between src and dest, network_simplex
            # doesn't handle multigraph (as of 1.5), so insert dummy nodes
            # in the middle of each extra edge as a workaround. (See
            # https://networkx.lanl.gov/trac/ticket/607.
            capacity, weight = chunk
            dummy_node = u'%s__%s__%s' % (src, dest, i)
            graph.add_edge(src, dummy_node, weight=weight, capacity=capacity,
                           creditline=creditline)
            graph.add_edge(dummy_node, dest)  # Zero weight, infinite capacity.
            # Dummy edge has no creditline, so can be ignored later.
            
    def _set_endpoint_demand(self, graph):
        "Add payer and recipient nodes with corresponding demands values."
        # XXX Convert decimal amounts to float for networkx.
        graph.node[self.payment.payer_id]['demand'] = (
            float(-self.payment.amount))
        graph.node[self.payment.recipient_id]['demand'] = (
            float(self.payment.amount))

    def __iter__(self):
        "Iterate through credit line links used for this payment."
        for src_node, node_flow_dict in self.flow_dict.iteritems():
            for dest_node, amount in node_flow_dict.iteritems():
                if amount > 0:
                    creditline = self.graph[src_node][dest_node].get(
                        'creditline')
                    if not creditline:  # Dummy edge.
                        continue
                    yield FlowLink(self.payment, creditline, amount)

class FlowLink(object):
    "A credit line link used for payment."
    def __init__(self, payment, creditline, amount):
        self.payment = payment
        self.creditline = creditline
        # Note: Amount is float here, so convert to Decimal.
        amount = float_to_decimal(amount)
        # Owner of this account is sending the flow => he should see negative
        # balance change.
        self.amount = -amount * creditline.bal_mult
        
    @property
    def account(self):
        return self.creditline.account

def float_to_decimal(amount):
    "Convert float to decimal in order to retain as much precision as possible."
    # Convert float to string with number of decimal places stored in db.
    float_interp_str = '%%.%df' % AmountField.SCALE  # '%.2f'
    amount_str = float_interp_str % amount
    return D(amount_str)
