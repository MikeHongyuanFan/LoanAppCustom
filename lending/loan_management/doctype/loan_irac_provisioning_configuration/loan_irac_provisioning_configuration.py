# Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

# import frappe
from frappe.model.document import Document


class LoanIRACProvisioningConfiguration(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		classification_code: DF.Link | None
		classification_name: DF.Data | None
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
		provision_rate: DF.Percent
		security_type: DF.Literal["Secured", "Unsecured", "Semi-Secured"]
	# end: auto-generated types

	pass
