# This code is part of Qiskit.
#
# (C) Copyright IBM 2022.
#
# This code is licensed under the Apache License, Version 2.0. You may
# obtain a copy of this license in the LICENSE.txt file in the root directory
# of this source tree or at http://www.apache.org/licenses/LICENSE-2.0.
#
# Any modifications or derivative works of this code must retain this
# copyright notice, and modified files need to carry a notice indicating
# that they have been altered from the originals.

"""Qiskit Runtime flexible session."""

from typing import Dict, Optional, Type, Union, Callable, Any
from types import TracebackType
from functools import wraps

from qiskit_ibm_runtime import QiskitRuntimeService
from .runtime_job import RuntimeJob
from .runtime_job_v2 import RuntimeJobV2
from .utils.result_decoder import ResultDecoder
from .ibm_backend import IBMBackend
from .utils.default_session import set_cm_session
from .utils.deprecation import deprecate_arguments, issue_deprecation_msg
from .utils.converters import hms_to_seconds


def _active_session(func):  # type: ignore
    """Decorator used to ensure the session is active."""

    @wraps(func)
    def _wrapper(self, *args, **kwargs):  # type: ignore
        if not self._active:
            raise RuntimeError("The session is closed.")
        return func(self, *args, **kwargs)

    return _wrapper


class Session:
    """Class for creating a Qiskit Runtime session.

    A Qiskit Runtime ``session`` allows you to group a collection of iterative calls to
    the quantum computer. A session is started when the first job within the session
    is started. Subsequent jobs within the session are prioritized by the scheduler.

    You can open a Qiskit Runtime session using this ``Session`` class and submit jobs
    to one or more primitives.

    For example::

        from qiskit.circuit import QuantumCircuit, QuantumRegister, ClassicalRegister
        from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager
        from qiskit_ibm_runtime import Session, SamplerV2 as Sampler

        service = QiskitRuntimeService()
        backend = service.least_busy(operational=True, simulator=False)

        # Bell Circuit
        qr = QuantumRegister(2, name="qr")
        cr = ClassicalRegister(2, name="cr")
        qc = QuantumCircuit(qr, cr, name="bell")
        qc.h(qr[0])
        qc.cx(qr[0], qr[1])
        qc.measure(qr, cr)

        pm = generate_preset_pass_manager(backend=backend, optimization_level=1)
        isa_circuit = pm.run(qc)

        with Session(backend=backend) as session:
            sampler = Sampler(session=session)
            job = sampler.run([isa_circuit])
            pub_result = job.result()[0]
            print(f"Sampler job ID: {job.job_id()}")
            print(f"Counts: {pub_result.data.cr.get_counts()}")
    """

    def __init__(
        self,
        service: Optional[QiskitRuntimeService] = None,
        backend: Optional[Union[str, IBMBackend]] = None,
        max_time: Optional[Union[int, str]] = None,
    ):  # pylint: disable=line-too-long
        """Session constructor.

        Args:
            service: Optional instance of the ``QiskitRuntimeService`` class.
                If ``None``, the service associated with the backend, if known, is used.
                Otherwise ``QiskitRuntimeService()`` is used to initialize
                your default saved account.
            backend: Optional instance of :class:`qiskit_ibm_runtime.IBMBackend` class or
                string name of backend. An instance of :class:`qiskit_ibm_provider.IBMBackend` will not work.
                If not specified, a backend will be selected automatically (IBM Cloud channel only).

            max_time: (EXPERIMENTAL setting, can break between releases without warning)
                Maximum amount of time, a runtime session can be open before being
                forcibly closed. Can be specified as seconds (int) or a string like "2h 30m 40s".
                This value must be less than the
                `system imposed maximum
                <https://docs.quantum.ibm.com/run/max-execution-time>`_.

        Raises:
            ValueError: If an input value is invalid.
        """

        if service is None:
            if isinstance(backend, IBMBackend):
                self._service = backend.service
            else:
                self._service = (
                    QiskitRuntimeService()
                    if QiskitRuntimeService.global_service is None
                    else QiskitRuntimeService.global_service
                )
        else:
            self._service = service

        if not backend:
            if self._service.channel == "ibm_quantum":
                raise ValueError('"backend" is required for ``ibm_quantum`` channel.')
            issue_deprecation_msg(
                "Not providing a backend is deprecated",
                "0.21.0",
                "Passing in a backend will be required, please provide a backend.",
            )

        self._instance = None

        self._active = True
        self._max_time = (
            max_time
            if max_time is None or isinstance(max_time, int)
            else hms_to_seconds(max_time, "Invalid max_time value: ")
        )

        if isinstance(backend, IBMBackend):
            self._instance = backend._instance
            sim_backend = backend.configuration().simulator
            backend = backend.name
        else:
            backend_obj = self._service.backend(backend)
            self._instance = backend_obj._instance
            sim_backend = backend_obj.configuration().simulator
        self._backend = backend

        if not sim_backend:
            self._session_id = self._create_session()
        else:
            self._session_id = None

    def _create_session(self) -> str:
        """Create a session."""
        session = self._service._api_client.create_session(
            self._backend, self._instance, self._max_time, self._service.channel
        )
        return session.get("id")

    @_active_session
    def run(
        self,
        program_id: str,
        inputs: Dict,
        options: Optional[Dict] = None,
        callback: Optional[Callable] = None,
        result_decoder: Optional[Type[ResultDecoder]] = None,
    ) -> Union[RuntimeJob, RuntimeJobV2]:
        """Run a program in the session.

        Args:
            program_id: Program ID.
            inputs: Program input parameters. These input values are passed
                to the runtime program.
            options: Runtime options that control the execution environment.
                See :class:`qiskit_ibm_runtime.RuntimeOptions` for all available options.
            callback: Callback function to be invoked for any interim results and final result.

        Returns:
            Submitted job.
        """

        options = options or {}

        if "instance" not in options:
            options["instance"] = self._instance

        options["backend"] = self._backend

        job = self._service.run(
            program_id=program_id,
            options=options,
            inputs=inputs,
            session_id=self._session_id,
            start_session=False,
            callback=callback,
            result_decoder=result_decoder,
        )

        if self._backend is None:
            self._backend = job.backend().name

        return job

    def cancel(self) -> None:
        """Cancel all pending jobs in a session."""
        self._active = False
        if self._session_id:
            self._service._api_client.cancel_session(self._session_id)

    def close(self) -> None:
        """Close the session so new jobs will no longer be accepted, but existing
        queued or running jobs will run to completion. The session will be terminated once there
        are no more pending jobs."""
        self._active = False
        if self._session_id:
            self._service._api_client.close_session(self._session_id)

    def backend(self) -> Optional[str]:
        """Return backend for this session.

        Returns:
            Backend for this session. None if unknown.
        """
        return self._backend

    def status(self) -> Optional[str]:
        """Return current session status.

        Returns:
            The current status of the session, including:
            Pending: Session is created but not active.
            It will become active when the next job of this session is dequeued.
            In progress, accepting new jobs: session is active and accepting new jobs.
            In progress, not accepting new jobs: session is active and not accepting new jobs.
            Closed: max_time expired or session was explicitly closed.
            None: status details are not available.
        """
        details = self.details()
        if details:
            state = details["state"]
            accepting_jobs = details["accepting_jobs"]
            if state in ["open", "inactive"]:
                return "Pending"
            if state == "active" and accepting_jobs:
                return "In progress, accepting new jobs"
            if state == "active" and not accepting_jobs:
                return "In progress, not accepting new jobs"
            return state.capitalize()

        return None

    def details(self) -> Optional[Dict[str, Any]]:
        """Return session details.

        Returns:
            A dictionary with the sessions details, including:
            id: id of the session.
            backend_name: backend used for the session.
            interactive_timeout: The maximum idle time (in seconds) between jobs that
            is allowed to occur before the session is deactivated.
            max_time: Maximum allowed time (in seconds) for the session, subject to plan limits.
            active_timeout: The maximum time (in seconds) a session can stay active.
            state: State of the session - open, active, inactive, or closed.
            accepting_jobs: Whether or not the session is accepting jobs.
            last_job_started: Timestamp of when the last job in the session started.
            last_job_completed: Timestamp of when the last job in the session completed.
            started_at: Timestamp of when the session was started.
            closed_at: Timestamp of when the session was closed.
            activated_at: Timestamp of when the session state was changed to active.
        """
        if self._session_id:
            response = self._service._api_client.session_details(self._session_id)
            if response:
                return {
                    "id": response.get("id"),
                    "backend_name": response.get("backend_name"),
                    "interactive_timeout": response.get("interactive_ttl"),
                    "max_time": response.get("max_ttl"),
                    "active_timeout": response.get("active_ttl"),
                    "state": response.get("state"),
                    "accepting_jobs": response.get("accepting_jobs"),
                    "last_job_started": response.get("last_job_started"),
                    "last_job_completed": response.get("last_job_completed"),
                    "started_at": response.get("started_at"),
                    "closed_at": response.get("closed_at"),
                    "activated_at": response.get("activated_at"),
                }
        return None

    @property
    def session_id(self) -> Optional[str]:
        """Return the session ID.

        Returns:
            Session ID. None if the backend is a simulator.
        """
        return self._session_id

    @property
    def service(self) -> QiskitRuntimeService:
        """Return service associated with this session.

        Returns:
            :class:`qiskit_ibm_runtime.QiskitRuntimeService` associated with this session.
        """
        return self._service

    @classmethod
    def from_id(
        cls,
        session_id: str,
        service: Optional[QiskitRuntimeService] = None,
        backend: Optional[Union[str, IBMBackend]] = None,
    ) -> "Session":
        """Construct a Session object with a given session_id

        Args:
            session_id: the id of the session to be created. This must be an already
                existing session id.
            service: instance of the ``QiskitRuntimeService`` class.
            backend: instance of :class:`qiskit_ibm_runtime.IBMBackend` class or
                string name of backend.

        Returns:
            A new Session with the given ``session_id``

        """
        if backend:
            deprecate_arguments("backend", "0.15.0", "Sessions do not support multiple backends.")

        session = cls(service, backend)
        session._session_id = session_id
        return session

    def __enter__(self) -> "Session":
        set_cm_session(self)
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> None:
        set_cm_session(None)
        self.close()