import logging
from collections import OrderedDict

from lxml import etree

from zeep import exceptions
from zeep.xsd import builtins as xsd_builtins
from zeep.xsd import const
from zeep.xsd.visitor import SchemaVisitor

logger = logging.getLogger(__name__)


class Schema(object):
    """A schema is a collection of schema documents."""

    def __init__(self, node=None, transport=None, location=None):
        self._transport = transport

        self._schemas = OrderedDict()
        self._prefix_map_auto = {}
        self._prefix_map_custom = {}

        if not isinstance(node, list):
            nodes = [node] if node is not None else []
        else:
            nodes = node
        self.add_documents(nodes, location)

    def add_documents(self, schema_nodes, location):
        documents = []
        for node in schema_nodes:
            document = self.create_new_document(node, location)
            documents.append(document)

        for document in documents:
            document.resolve()

        self._prefix_map_auto = self._create_prefix_map()

    def __repr__(self):
        if self._schemas:
            main_doc = next(iter(self._schemas.values()))
            location = main_doc._location
        else:
            location = '<none>'
        return '<Schema(location=%r)>' % location

    @property
    def prefix_map(self):
        retval = {}
        retval.update(self._prefix_map_custom)
        retval.update({
            k: v for k, v in self._prefix_map_auto.items()
            if v not in retval.values()
        })
        return retval

    @property
    def is_empty(self):
        """Boolean to indicate if this schema contains any types or elements"""
        return all(schema.is_empty for schema in self._schemas.values())

    @property
    def namespaces(self):
        return set(self._schemas.keys())

    @property
    def elements(self):
        """Yield all globla xsd.Type objects"""
        for schema in self._schemas.values():
            for element in schema._elements.values():
                yield element

    @property
    def types(self):
        """Yield all globla xsd.Type objects"""
        for schema in self._schemas.values():
            for type_ in schema._types.values():
                yield type_

    def get_element(self, qname):
        """Return a global xsd.Element object with the given qname"""
        qname = self._create_qname(qname)
        if qname.text in xsd_builtins.default_elements:
            return xsd_builtins.default_elements[qname]

        # Handle XSD namespace items
        if qname.namespace == const.NS_XSD:
            try:
                return xsd_builtins.default_elements[qname]
            except KeyError:
                raise exceptions.LookupError("No such type %r" % qname.text)

        try:
            schema = self._get_schema_document(qname.namespace)
            return schema.get_element(qname)
        except exceptions.NamespaceError:
            raise exceptions.NamespaceError((
                "Unable to resolve element %s. " +
                "No schema available for the namespace %r."
            ) % (qname.text, qname.namespace))

    def get_type(self, qname, fail_silently=False):
        """Return a global xsd.Type object with the given qname"""
        qname = self._create_qname(qname)

        # Handle XSD namespace items
        if qname.namespace == const.NS_XSD:
            try:
                return xsd_builtins.default_types[qname]
            except KeyError:
                raise exceptions.LookupError("No such type %r" % qname.text)

        try:
            schema = self._get_schema_document(qname.namespace)
            return schema.get_type(qname)
        except exceptions.NamespaceError:
            message = (
                "Unable to resolve type %s. " +
                "No schema available for the namespace %r."
            ) % (qname.text, qname.namespace)

            if fail_silently:
                logger.info(message)
            else:
                raise exceptions.NamespaceError(message)

    def get_group(self, qname):
        """Return a global xsd.Group object with the given qname"""
        qname = self._create_qname(qname)
        try:
            schema = self._get_schema_document(qname.namespace)
            return schema.get_group(qname)
        except exceptions.NamespaceError:
            raise exceptions.NamespaceError((
                "Unable to resolve group %s. " +
                "No schema available for the namespace %r."
            ) % (qname.text, qname.namespace))

    def get_attribute(self, qname):
        """Return a global xsd.attributeGroup object with the given qname"""
        qname = self._create_qname(qname)
        try:
            schema = self._get_schema_document(qname.namespace)
            return schema.get_attribute(qname)
        except exceptions.NamespaceError:
            raise exceptions.NamespaceError((
                "Unable to resolve attribute %s. " +
                "No schema available for the namespace %r."
            ) % (qname.text, qname.namespace))

    def get_attribute_group(self, qname):
        """Return a global xsd.attributeGroup object with the given qname"""
        qname = self._create_qname(qname)
        try:
            schema = self._get_schema_document(qname.namespace)
            return schema.get_attribute_group(qname)
        except exceptions.NamespaceError:
            raise exceptions.NamespaceError((
                "Unable to resolve attributeGroup %s. " +
                "No schema available for the namespace %r."
            ) % (qname.text, qname.namespace))

    def merge(self, schema):
        """Merge an other XSD schema in this one"""
        for namespace, _schema in schema._schemas.items():
            self._schemas[namespace] = _schema
        self._prefix_map_auto = self._create_prefix_map()

    def _create_qname(self, name):
        """Create an `lxml.etree.QName()` object for the given qname string.

        This also expands the shorthand notation.

        """
        if isinstance(name, etree.QName):
            return name

        if not name.startswith('{') and ':' in name and self._prefix_map_auto:
            prefix, localname = name.split(':', 1)
            if prefix in self._prefix_map_custom:
                return etree.QName(self._prefix_map_custom[prefix], localname)
            elif prefix in self._prefix_map_auto:
                return etree.QName(self._prefix_map_auto[prefix], localname)
            else:
                raise ValueError(
                    "No namespace defined for the prefix %r" % prefix)
        else:
            return etree.QName(name)

    def _create_prefix_map(self):
        prefix_map = {
            'xsd': 'http://www.w3.org/2001/XMLSchema',
        }
        for i, namespace in enumerate(self._schemas.keys()):
            if namespace is None:
                continue
            prefix_map['ns%d' % i] = namespace
        return prefix_map

    def set_ns_prefix(self, prefix, namespace):
        self._prefix_map_custom[prefix] = namespace

    def get_ns_prefix(self, prefix):
        try:
            try:
                return self._prefix_map_custom[prefix]
            except KeyError:
                return self._prefix_map_auto[prefix]
        except KeyError:
            raise ValueError("No such prefix %r" % prefix)

    def create_new_document(self, node, url, base_url=None):
        namespace = node.get('targetNamespace') if node is not None else None
        if base_url is None:
            base_url = url

        schema = SchemaDocument(namespace, self, url, base_url)
        self._add_schema_document(schema)
        schema.load(node)
        return schema

    def _has_schema_document(self, namespace):
        return namespace in self._schemas

    def _add_schema_document(self, document):
        logger.info("Add document with tns %s to schema %s", document._target_namespace, id(self))
        self._schemas[document._target_namespace] = document

    def _get_schema_document(self, namespace, fail_silently=False):
        if namespace not in self._schemas:
            if fail_silently:
                return
            raise exceptions.NamespaceError(
                "No schema available for the namespace %r" % namespace)
        return self._schemas[namespace]


class SchemaDocument(object):
    def __init__(self, namespace, schema, location, base_url):
        logger.debug("Init schema document for %r", location)

        # Internal
        self._schema = schema
        self._base_url = base_url or location
        self._location = location
        self._target_namespace = namespace
        self._elm_instances = []

        self._attribute_groups = {}
        self._attributes = {}
        self._elements = {}
        self._groups = {}
        self._types = {}

        self._imports = OrderedDict()
        self._element_form = 'unqualified'
        self._attribute_form = 'unqualified'
        self._resolved = False
        # self._xml_schema = None

    def load(self, node):
        if node is None:
            return

        if not self._schema._has_schema_document(self._target_namespace):
            raise RuntimeError(
                "The document needs to be registered in the schema before " +
                "it can be loaded")

        # Disable XML schema validation for now
        # if len(node) > 0:
        #     self.xml_schema = etree.XMLSchema(node)
        visitor = SchemaVisitor(self)
        visitor.visit_schema(node)

    def __repr__(self):
        return '<SchemaDocument(location=%r, tns=%r, is_empty=%r)>' % (
            self._location, self._target_namespace, self.is_empty)

    def resolve(self):
        logger.info("Resolving in schema %s", self)

        if self._resolved:
            return
        self._resolved = True

        for schema in self._imports.values():
            schema.resolve()

        def _resolve_dict(val):
            for key, obj in val.items():
                new = obj.resolve()
                assert new is not None, "resolve() should return an object"
                val[key] = new

        _resolve_dict(self._attribute_groups)
        _resolve_dict(self._attributes)
        _resolve_dict(self._elements)
        _resolve_dict(self._groups)
        _resolve_dict(self._types)

        for element in self._elm_instances:
            element.resolve()
        self._elm_instances = []

    def register_import(self, namespace, schema):
        self._imports[namespace] = schema

    def is_imported(self, namespace):
        return namespace in self._imports

    def register_type(self, name, value):
        assert not isinstance(value, type)
        assert value is not None

        if isinstance(name, etree.QName):
            name = name.text
        logger.debug("register_type(%r, %r)", name, value)
        self._types[name] = value

    def register_element(self, name, value):
        if isinstance(name, etree.QName):
            name = name.text
        logger.debug("register_element(%r, %r)", name, value)
        self._elements[name] = value

    def register_group(self, name, value):
        if isinstance(name, etree.QName):
            name = name.text
        logger.debug("register_group(%r, %r)", name, value)
        self._groups[name] = value

    def register_attribute(self, name, value):
        if isinstance(name, etree.QName):
            name = name.text
        logger.debug("register_attribute(%r, %r)", name, value)
        self._attributes[name] = value

    def register_attribute_group(self, name, value):
        if isinstance(name, etree.QName):
            name = name.text
        logger.debug("register_attribute_group(%r, %r)", name, value)
        self._attribute_groups[name] = value

    def get_type(self, qname):
        """Return a xsd.Type object from this schema"""
        try:
            return self._types[qname]
        except KeyError:
            known_items = ', '.join(self._types.keys())
            raise exceptions.LookupError((
                "No type '%s' in namespace %s. " +
                "Available types are: %s"
            ) % (qname.localname, qname.namespace, known_items or ' - '))

    def get_element(self, qname):
        """Return a xsd.Element object from this schema"""
        try:
            return self._elements[qname]
        except KeyError:
            known_items = ', '.join(self._elements.keys())
            raise exceptions.LookupError((
                "No element '%s' in namespace %s. " +
                "Available elements are: %s"
            ) % (qname.localname, qname.namespace, known_items or ' - '))

    def get_group(self, qname):
        """Return a xsd.Group object from this schema"""
        try:
            return self._groups[qname]
        except KeyError:
            known_items = ', '.join(self._groups.keys())
            raise exceptions.LookupError((
                "No group '%s' in namespace %s. " +
                "Available attributes are: %s"
            ) % (qname.localname, qname.namespace, known_items or ' - '))

    def get_attribute(self, qname):
        """Return a xsd.Attribute object from this schema"""
        try:
            return self._attributes[qname]
        except KeyError:
            known_items = ', '.join(self._attributes.keys())
            raise exceptions.LookupError((
                "No attribute '%s' in namespace %s. " +
                "Available attributes are: %s"
            ) % (qname.localname, qname.namespace, known_items or ' - '))

    def get_attribute_group(self, qname):
        """Return a xsd.AttributeGroup object from this schema"""
        try:
            return self._attribute_groups[qname]
        except KeyError:
            known_items = ', '.join(self._attribute_groups.keys())
            raise exceptions.LookupError((
                "No attributeGroup '%s' in namespace %s. " +
                "Available attributeGroups are: %s"
            ) % (qname.localname, qname.namespace, known_items or ' - '))

    @property
    def is_empty(self):
        return not bool(self._imports or self._types or self._elements)
