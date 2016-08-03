import React from 'react';
import {History} from 'react-router';

import ApiMixin from '../../mixins/apiMixin';
import countryCodes from '../../utils/countryCodes';

import GeoMap from './geoMap';
import LoadingError from '../../components/loadingError';
import LoadingIndicator from '../../components/loadingIndicator';

const GroupLocations = React.createClass({
  mixins: [
    ApiMixin,
    History
  ],

  getInitialState() {
    return {
      loading: true,
      error: false,
      data: null
    };
  },

  componentWillMount() {
    this.fetchData();
  },

  fetchData() {
    let url = '/issues/' + this.props.params.groupId + '/tags/user.location/';
    this.setState({
      loading: true,
      error: false
    });

    this.api.request(url, {
      success: (data, _, jqXHR) => {
        this.setState({
          data: data,
          error: false,
          loading: false
        });
      },
      error: () => {
        this.setState({
          error: true,
          loading: false
        });
      }
    });
  },

  render() {
    if (this.state.loading)
      return <LoadingIndicator/>;
    if (this.state.error)
      return <LoadingError/>;

    let series = this.state.data.topValues.map(tag => [countryCodes[tag.value], tag.count]);
    return <GeoMap series={series}/>;
  }
});

export default GroupLocations;
