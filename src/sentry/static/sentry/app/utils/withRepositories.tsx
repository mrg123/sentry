import React from 'react';
import Reflux from 'reflux';
import createReactClass from 'create-react-class';

import {Client} from 'app/api';
import {Repository} from 'app/types';
import getDisplayName from 'app/utils/getDisplayName';
import RepositoryStore from 'app/stores/repositoryStore';
import {getRepositories} from 'app/actionCreators/repositories';

type DependentProps = {
  api: Client;
  orgSlug: string;
  projectSlug: string;
  releaseVersion: string;
};

type InjectedProps = {
  repositories: Repository[] | undefined;
  repositoriesLoading: boolean | undefined;
  repositoriesError: Error | undefined;
};

const withRepositories = <P extends InjectedProps>(
  WrappedComponent: React.ComponentType<P>
) =>
  createReactClass<
    Omit<P, keyof InjectedProps> & Partial<InjectedProps> & DependentProps,
    InjectedProps
  >({
    displayName: `withRepositories(${getDisplayName(WrappedComponent)})`,
    mixins: [Reflux.listenTo(RepositoryStore, 'onStoreUpdate') as any],

    getInitialState() {
      const {orgSlug} = this.props as P & DependentProps;
      const repoData = RepositoryStore.get(orgSlug);

      return {
        repositories: undefined,
        repositoriesLoading: undefined,
        repositoriesError: undefined,
        ...repoData,
      };
    },

    componentDidMount() {
      this.fetchRepos();
    },

    fetchRepos() {
      const {api, orgSlug} = this.props as P & DependentProps;
      const repoData = RepositoryStore.get(orgSlug);

      if (!repoData.repositories && !repoData.repositoriesLoading) {
        // HACK(leedongwei): Actions fired by the ActionCreators are queued to
        // the back of the event loop, allowing another getRepo for the same
        // repo to be fired before the loading state is updated in store.
        // This hack short-circuits that and update the state immediately.
        RepositoryStore.state.repositoriesLoading = true;
        RepositoryStore.state.orgSlug = orgSlug;

        getRepositories(api, {orgSlug});
      }
    },

    onStoreUpdate() {
      const {orgSlug} = this.props as P & DependentProps;
      const repoData = RepositoryStore.get(orgSlug);

      this.setState({...repoData});
    },

    render() {
      return <WrappedComponent {...(this.props as P & DependentProps)} {...this.state} />;
    },
  });

export default withRepositories;
